from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import httpx
import pytest
from evaluation.budget import EvaluationBudget, BudgetError
from evaluation.postprocess_validation import call

URL='https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'


def budget_file(tmp_path,**changes):
    cfg={'max_calls':30,'max_input_bytes':100000,'max_output_tokens':5000,
         'max_output_tokens_per_call':128,'max_estimated_cost_cny':'1',
         'settle_successful_usage':True,'models':{'qwen-plus':{'input_per_million_cny':'1','output_per_million_cny':'2'}}}
    cfg.update(changes);path=tmp_path/'usage.json';path.write_text(json.dumps(cfg));return path


def client(monkeypatch,*,status=200):
    monkeypatch.setenv('DASHSCOPE_API_KEY','offline-placeholder')
    return httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(status,json={
        'output':{'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]},
        'usage':{'input_tokens':4,'output_tokens':2}})),trust_env=False)


def task(http):return call(http,'qwen-plus',[{'role':'user','content':'test'}],64,1,32768)


def test_success_settlement_is_explicit_and_limits_never_refund(tmp_path,monkeypatch):
    with EvaluationBudget(budget_file(tmp_path,max_calls=1)) as b,client(monkeypatch) as http:
        result=task(http);full=b.cost
        assert full>Decimal('0.000008') and not b.events[0].get('settled')
        b.settle_successful_result(result)
        assert b.cost==Decimal('0.000008') and b.calls==1 and b.output_tokens==64
        assert b.input_bytes==b.events[0]['input_bytes']
        with pytest.raises(BudgetError):task(http)
    log=json.loads(b.ledger.read_text());assert Decimal(log['estimated_cost_cny_reservation_sum'])==full
    assert log['estimated_cost_cny_exposure']=='0.000008'


def test_failed_http_keeps_full_reservation(tmp_path,monkeypatch):
    with EvaluationBudget(budget_file(tmp_path)) as b,client(monkeypatch,status=500) as http:
        with pytest.raises(httpx.HTTPStatusError):task(http)
        assert b.calls==1 and not b.events[0].get('settled')
        assert b.cost==Decimal(b.events[0]['estimated_cost_cny'])


@pytest.mark.parametrize('mutation',[
    {'budget_attempt':999}, {'budget_attempt':True}, {'input_sha256':'wrong'},
    {'usage':{'input_tokens':True,'output_tokens':2}},
    {'usage':{'input_tokens':4,'output_tokens':-1}},
    {'usage':{'input_tokens':999999,'output_tokens':2}},
    {'usage':{'input_tokens':4,'output_tokens':65}}, {'finish_reason':'length'},
])
def test_invalid_receipt_stops_without_refund(tmp_path,monkeypatch,mutation):
    with EvaluationBudget(budget_file(tmp_path)) as b,client(monkeypatch) as http:
        result=task(http);reserved=b.cost;result.update(mutation)
        with pytest.raises(BudgetError):b.settle_successful_result(result)
        assert b.stopped and b.cost==reserved


def test_receipt_cannot_settle_twice(tmp_path,monkeypatch):
    with EvaluationBudget(budget_file(tmp_path)) as b,client(monkeypatch) as http:
        result=task(http);b.settle_successful_result(result);cost=b.cost
        with pytest.raises(BudgetError):b.settle_successful_result(result)
        assert b.cost==cost and b.stopped


def test_default_legacy_budget_does_not_change_cost(tmp_path,monkeypatch):
    with EvaluationBudget(budget_file(tmp_path,settle_successful_usage=False)) as b,client(monkeypatch) as http:
        result=task(http);cost=b.cost
        assert 'budget_attempt' not in result
        b.settle_successful_result(result)
        assert b.cost==cost


def test_parallel_receipts_are_bound_to_exact_requests(tmp_path,monkeypatch):
    with EvaluationBudget(budget_file(tmp_path)) as b,client(monkeypatch) as http:
        def worker(i):
            result=call(http,'qwen-plus',[{'role':'user','content':str(i)}],64,1,32768)
            b.settle_successful_result(result)
        with ThreadPoolExecutor(max_workers=5) as pool:list(pool.map(worker,range(20)))
        assert b.calls==20 and all(e['settled'] for e in b.events)
        assert b.cost==20*Decimal('0.000008') and b.output_tokens==1280
