from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import sys

import httpx
import pytest
import requests

from evaluation.budget import EvaluationBudget, BudgetError, require_budget


URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


def config(tmp_path, **overrides):
    data = {"max_calls":10,"max_input_bytes":100000,"max_output_tokens":10000,
            "max_output_tokens_per_call":1024,"max_estimated_cost_cny":"1",
            "models":{"qwen-plus":{"input_per_million_cny":"1","output_per_million_cny":"2"},
                      "text-embedding-v4":{"input_per_million_cny":"1","output_per_million_cny":"0"},
                      "qwen3-rerank":{"input_per_million_cny":"1","output_per_million_cny":"0"}}}
    data.update(overrides)
    p=tmp_path/'approved-budget.json'
    p.write_text(json.dumps(data),encoding='utf-8')
    return p


def body(model="qwen-plus", content="test"):
    return {"model":model,"input":{"messages":[{"role":"user","content":content}]},
            "parameters":{"max_tokens":64}}


def client(calls, *, status=200):
    def send(request):
        calls.append(request)
        return httpx.Response(status,json={"ok":True})
    return httpx.Client(transport=httpx.MockTransport(send),trust_env=False)


def test_httpx_call_cap_and_single_use_ledger(tmp_path):
    cfg=config(tmp_path,max_calls=1);calls=[]
    with EvaluationBudget(cfg) as budget,client(calls) as http:
        http.post(URL,json=body())
        with pytest.raises(BudgetError):http.post(URL,json=body())
    assert len(calls)==budget.calls==1
    log=json.loads(budget.ledger.read_text())
    assert log['stopped'] and log['calls_reserved']==1
    with pytest.raises(BudgetError):
        with EvaluationBudget(cfg):pass
    assert 'content' not in budget.ledger.read_text() and 'Bearer' not in budget.ledger.read_text()


@pytest.mark.parametrize("limits",[
    {"max_input_bytes":1}, {"max_output_tokens":63},
    {"max_output_tokens_per_call":63},{"max_estimated_cost_cny":"0"},
])
def test_input_output_and_money_limits_stop_before_transport(tmp_path,limits):
    calls=[]
    with EvaluationBudget(config(tmp_path,**limits)),client(calls) as http:
        with pytest.raises(BudgetError):http.post(URL,json=body())
    assert calls==[]


def test_failed_attempt_is_charged_before_retry(tmp_path):
    calls=[]
    with EvaluationBudget(config(tmp_path,max_calls=1)) as budget,client(calls,status=500) as http:
        assert http.post(URL,json=body()).status_code==500
        with pytest.raises(BudgetError):http.post(URL,json=body())
    assert len(calls)==1 and budget.output_tokens==64


def test_requests_transport_and_sdk_retry_share_the_same_cap(tmp_path,monkeypatch):
    import dashscope.api_entities.http_request as native
    from dashscope import Generation,TextEmbedding
    calls=[]
    class FakeAdapter(requests.adapters.BaseAdapter):
        def send(self,request,**kwargs):
            calls.append(json.loads(request.body))
            if len(calls)==1:
                raise requests.ConnectionError("simulated dropped connection")
            r=requests.Response();r.status_code=200;r.url=request.url
            r.headers['Content-Type']='application/json'
            payload={"request_id":"fake", "usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2},
                     "output":{"choices":[{"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}],
                               "embeddings":[{"text_index":0,"embedding":[0.1]}]}}
            r._content=json.dumps(payload).encode();return r
        def close(self):pass
    session=requests.Session();session.mount('https://',FakeAdapter())
    monkeypatch.setattr(native,'_shared_sync_session',session)
    with EvaluationBudget(config(tmp_path,max_calls=3)) as budget:
        result=Generation.call(model='qwen-plus',messages=[{'role':'user','content':'test'}],
                               max_tokens=64,result_format='message',api_key='test-key')
        assert result.status_code==200
        embedding=TextEmbedding.call(model='text-embedding-v4',input=['test'],api_key='test-key')
        assert embedding.status_code==200
        with pytest.raises(BudgetError):
            Generation.call(model='qwen-plus',messages=[{'role':'user','content':'test'}],
                            max_tokens=64,api_key='test-key')
    assert len(calls)==budget.calls==3


def test_rerank_attempt_is_counted_even_with_fallback(tmp_path,monkeypatch):
    from langchain_core.documents import Document
    from src.services.rerank import Reranker
    monkeypatch.setenv('DASHSCOPE_API_KEY','test-key')
    calls=[]
    def send(request):calls.append(request);return httpx.Response(500)
    reranker=Reranker(transport=httpx.MockTransport(send))
    docs=[Document(id=str(i),page_content='test') for i in range(2)]
    with EvaluationBudget(config(tmp_path,max_calls=1)) as budget:
        assert reranker.rerank('query',docs).status=='fallback'
        with pytest.raises(BudgetError):reranker.rerank('query',docs)
    assert len(calls)==budget.calls==1


def test_concurrent_attempts_cannot_overspend_call_cap(tmp_path):
    calls=[]
    with EvaluationBudget(config(tmp_path,max_calls=3)) as budget,client(calls) as http:
        def attempt(_):
            try:http.post(URL,json=body());return True
            except BudgetError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            success=list(pool.map(attempt,range(16)))
    assert sum(success)==len(calls)==budget.calls==3


@pytest.mark.parametrize("payload,url",[(body('unapproved'),URL),(body(),'https://other.invalid/api/v1/services/aigc'),
    ({'model':'qwen-plus','input':{'image':'unsupported'}},URL),({'model':'qwen-plus','input':{'messages':[]}},URL)])
def test_unknown_models_endpoints_and_inputs_do_not_send(tmp_path,payload,url):
    calls=[]
    with EvaluationBudget(config(tmp_path)),client(calls) as http:
        with pytest.raises(BudgetError):http.post(url,json=payload)
    assert not calls


def test_rich_inputs_and_tools_are_not_counted_as_plain_text(tmp_path):
    calls=[];payload=body();payload['input']['image']='unsupported'
    with EvaluationBudget(config(tmp_path)),client(calls) as http:
        with pytest.raises(BudgetError):http.post(URL,json=payload)
    assert not calls


@pytest.mark.parametrize("change",[{'max_calls':True},{'max_calls':0},{'max_estimated_cost_cny':'NaN'},
    {'max_input_bytes':-1},{'models':{}},{'models':{'qwen-plus':{'input_per_million_cny':0,'output_per_million_cny':1}}}])
def test_invalid_budget_rejected(tmp_path,change):
    with pytest.raises(BudgetError):EvaluationBudget(config(tmp_path,**change))


@pytest.mark.parametrize("stage",['generate','validate','retrieve','answer','judge','audit'])
def test_benchmark_cli_defaults_to_zero_paid_calls(tmp_path,monkeypatch,stage):
    from evaluation import benchmark
    root=tmp_path/'not-created'
    monkeypatch.setattr(sys,'argv',['benchmark',stage,'--root',str(root)])
    with pytest.raises(SystemExit) as error:benchmark.main()
    assert error.value.code==2 and not root.exists()


def test_evaluate_cli_defaults_to_zero_paid_calls(tmp_path,monkeypatch):
    from evaluation import evaluate
    monkeypatch.setattr(sys,'argv',['evaluate','--output',str(tmp_path/'not-created.json')])
    with pytest.raises(SystemExit) as error:evaluate.main()
    assert error.value.code==2 and not (tmp_path/'not-created.json').exists()


def test_direct_chat_call_requires_budget():
    from evaluation.benchmark import chat
    with pytest.raises(BudgetError):chat('test',{})
    with pytest.raises(BudgetError):require_budget()


def test_benchmark_retry_stops_at_wire_budget(tmp_path,monkeypatch):
    from evaluation import benchmark
    calls=[]
    transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(429))
    original=httpx.Client.__init__
    def init(self,*args,**kwargs):
        kwargs.update(transport=transport,trust_env=False)
        original(self,*args,**kwargs)
    monkeypatch.setattr(httpx.Client,'__init__',init)
    monkeypatch.setattr(benchmark.time,'sleep',lambda _:None)
    monkeypatch.setenv('DASHSCOPE_API_KEY','test-key')
    with EvaluationBudget(config(tmp_path,max_calls=1)):
        with pytest.raises(BudgetError):benchmark.chat('test',{},max_tokens=64)
    assert len(calls)==1


def test_requests_retry_configuration_is_restored_after_run(tmp_path,monkeypatch):
    session=requests.Session();adapter=session.get_adapter(URL);original=adapter.max_retries
    monkeypatch.setattr(adapter,'send',lambda request,**kwargs: requests.Response())
    with EvaluationBudget(config(tmp_path)):
        session.post(URL,json=body())
        assert adapter.max_retries.total==0
    assert adapter.max_retries is original


@pytest.mark.parametrize('extra',[
    {'enable_thinking':True},{'n':2},{'best_of':2},
])
def test_unbounded_generation_modes_are_blocked(tmp_path,extra):
    calls=[];payload=body();payload['parameters'].update(extra)
    with EvaluationBudget(config(tmp_path)),client(calls) as http:
        with pytest.raises(BudgetError):http.post(URL,json=payload)
    assert calls==[]


def test_async_requests_are_rejected_before_transport(tmp_path):
    # The guard rejects before its first await; no event-loop sockets are needed.
    with EvaluationBudget(config(tmp_path)) as budget:
        coroutine=httpx.AsyncClient.send(None,httpx.Request('POST',URL,json=body()))
        with pytest.raises(BudgetError):coroutine.send(None)
        coroutine.close()
    assert budget.calls==0


def test_malformed_request_stops_budget_without_sending(tmp_path):
    calls=[]
    with EvaluationBudget(config(tmp_path)) as budget,client(calls) as http:
        with pytest.raises(BudgetError):http.post(URL,content=b'not-json')
        with pytest.raises(BudgetError):http.post(URL,json=body())
    assert budget.stopped and not calls


def test_missing_budget_file_is_rejected_without_creating_a_ledger(tmp_path):
    with pytest.raises(BudgetError):EvaluationBudget(tmp_path/'missing.json')
    assert list(tmp_path.iterdir())==[]


def test_httpx_internal_retries_are_rejected_before_network(tmp_path):
    with EvaluationBudget(config(tmp_path)) as budget, httpx.Client(
            transport=httpx.HTTPTransport(retries=1),trust_env=False) as http:
        with pytest.raises(BudgetError):http.post(URL,json=body())
    assert budget.calls==0


def test_unrecognized_transport_cannot_hide_its_own_retries(tmp_path):
    called=[]
    class OtherTransport(httpx.BaseTransport):
        def handle_request(self,request):
            called.append(request)
            return httpx.Response(200)
    with EvaluationBudget(config(tmp_path)), httpx.Client(transport=OtherTransport(),trust_env=False) as http:
        with pytest.raises(BudgetError):http.post(URL,json=body())
    assert called==[]
