from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tarfile

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from langchain_core.chat_history import InMemoryChatMessageHistory
import pytest

from evaluation import intent_workflow as experiment
from src.services.context import EvidenceContextBuilder
from src.services.rag import RagService


@pytest.fixture
def archived_workflow_prompt(monkeypatch):
    from src.services import prompts
    archive=Path(__file__).resolve().parents[3]/'docs/validation/intent-workflow-20261120-v1.tar.gz'
    with tarfile.open(archive) as tf:
        systems=json.load(tf.extractfile('experiment/prompts.json'))
    monkeypatch.setattr(prompts,'CONTEXT_SYSTEM_PROMPT',systems['optimized'])
    return systems


def test_default_prompt_restored_to_archived_baseline():
    from src.services.prompts import CONTEXT_SYSTEM_PROMPT
    archive=Path(__file__).resolve().parents[3]/'docs/validation/intent-workflow-20261120-v1.tar.gz'
    with tarfile.open(archive) as tf:
        systems=json.load(tf.extractfile('experiment/prompts.json'))
    assert CONTEXT_SYSTEM_PROMPT==systems['baseline']
    assert CONTEXT_SYSTEM_PROMPT!=systems['optimized']


def test_prepare_refuses_an_identical_prompt_without_creating_run(tmp_path,monkeypatch):
    from src.services.prompts import CONTEXT_SYSTEM_PROMPT
    source=('CONTEXT_SYSTEM_PROMPT='+repr(CONTEXT_SYSTEM_PROMPT)).encode('utf-8')
    monkeypatch.setattr(experiment.subprocess,'check_output',lambda *a,**kw:source)
    root=tmp_path/'identical'
    with pytest.raises(ValueError,match='identical'):
        experiment.prepare(root,tmp_path/'not-read.tar.gz','3897dd4')
    assert not root.exists()


def test_prompt_versions_do_not_change_user_data_sources_or_history():
    class Retriever:
        def invoke(self,query):return [Document(page_content='请重启APP。',metadata={'source':'手册.txt'})]
    captures=[]
    def model(value):
        captures.append(experiment.serialize(value.to_messages()))
        return '{"decision":"answer","claims":[{"text":"重启APP。","quote":"请重启APP。"}]}'
    outputs=[]
    for system in ['固定规则A','固定规则B']:
        history=InMemoryChatMessageHistory()
        service=RagService(Retriever(),RunnableLambda(model),lambda _:history,
            context_entries_enabled=True,context_system_prompt=system,
            context_builder=EvidenceContextBuilder(lambda:[],()))
        outputs.append(list(service.stream_answer('怎么处理“参数”？','same-session')))
        assert history.messages[0].content=='怎么处理“参数”？'
        assert history.messages[-1].content=='重启APP。 [S1]'
    assert captures[0][0]['content']=='固定规则A' and captures[1][0]['content']=='固定规则B'
    assert captures[0][1:]==captures[1][1:] and outputs[0]==outputs[1]


def test_historical_prompt_is_parsed_without_executing_code():
    assert experiment.extract_prompt('raise RuntimeError("must not run")\nCONTEXT_SYSTEM_PROMPT="literal"')=='literal'
    with pytest.raises(ValueError):experiment.extract_prompt('CONTEXT_SYSTEM_PROMPT=__import__("os").getcwd()')


def test_prepare_freezes_twenty_paired_inputs_without_network(tmp_path,monkeypatch,archived_workflow_prompt):
    archive=Path(__file__).resolve().parents[3]/'docs/validation/phase1-context-300-20261116-v1.tar.gz'
    with tarfile.open(archive) as tf:source=tf.extractfile('backend/src/services/prompts.py').read()
    monkeypatch.setattr(experiment.subprocess,'check_output',lambda *a,**kw:source)
    root=tmp_path/'prepared'
    result=experiment.prepare(root,archive,'3897dd4')
    assert result=={'questions':20,'prepared_messages':40,'source_parity':20,'baseline_original_messages':20,'paid_calls':0}
    data,protocol,_=experiment.checked(root)
    assert set(Counter(q['source'] for q in data['questions']).values())=={4}
    assert sum(j['arms'][0]=='baseline' for j in protocol['execution'])==10
    assert len(list((root/'messages').glob('*.json')))==40
    assert not (root/'answers').exists()
    with pytest.raises(FileExistsError):experiment.prepare(root,archive,'3897dd4')
    # An edited prompt cannot be silently used in a frozen paid experiment.
    (root/'prompts.json').write_text('{}',encoding='utf-8')
    with pytest.raises(AssertionError):experiment.checked(root)


def test_answer_requires_explicit_budget_before_reading_inputs(tmp_path,monkeypatch):
    root=tmp_path/'does-not-exist'
    monkeypatch.setattr(sys,'argv',['intent_workflow','answer','--root',str(root)])
    with pytest.raises(SystemExit) as error:experiment.main()
    assert error.value.code==2 and not root.exists()


def test_source_changes_invalidate_a_prepared_run(tmp_path,monkeypatch):
    p=tmp_path/'source-hashes.json';p.write_text('{"source":"before"}')
    experiment.write(tmp_path/'inputs-manifest.json',{'source-hashes.json':hashlib.sha256(p.read_bytes()).hexdigest()})
    monkeypatch.setattr(experiment,'source_hashes',lambda:{'source':'after'})
    with pytest.raises(AssertionError,match='Source changed'):experiment.checked(tmp_path)


def test_answer_records_both_arms_and_resumes_only_matching_checkpoints(tmp_path,monkeypatch,archived_workflow_prompt):
    from langchain_community.chat_models import tongyi
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    calls=[]
    class OfflineTongyi(tongyi.ChatTongyi):
        def _generate(self,messages,stop=None,run_manager=None,**kwargs):
            assert kwargs['response_format']=={'type':'json_object'}
            calls.append(experiment.serialize(messages))
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content='{"decision":"insufficient","claims":[],"question":""}'),
                generation_info={'finish_reason':'stop','token_usage':{'input_tokens':10,'output_tokens':5}},
            )])

    monkeypatch.setenv('DASHSCOPE_API_KEY','offline-test-key')
    monkeypatch.setattr(tongyi,'ChatTongyi',OfflineTongyi)
    monkeypatch.setattr(experiment,'require_budget',lambda:object())
    archive=Path(__file__).resolve().parents[3]/'docs/validation/phase1-context-300-20261116-v1.tar.gz'
    with tarfile.open(archive) as tf:source=tf.extractfile('backend/src/services/prompts.py').read()
    monkeypatch.setattr(experiment.subprocess,'check_output',lambda *a,**kw:source)
    root=tmp_path/'paired'
    experiment.prepare(root,archive,'3897dd4')
    def deny(*a,**kw):raise AssertionError('Offline model must not open a connection')
    monkeypatch.setattr(experiment.socket.socket,'connect',deny)
    monkeypatch.setattr(experiment.socket.socket,'connect_ex',deny)
    experiment.answer(root)
    assert len(calls)==40
    paths=list((root/'answers').glob('*.json'))
    assert len(paths)==40
    for path in paths:
        result=experiment.read(path)
        assert result['raw_generation'].startswith('{"decision"')
        assert result['generation_info']['finish_reason']=='stop'
        assert result['sources']==experiment.read(root/'messages'/path.name)['sources']
    experiment.answer(root)
    assert len(calls)==40
    first=experiment.read(root/'protocol.json')['execution'][0]
    path=root/'answers'/f"{first['id']}-{first['arms'][0]}.json"
    result=experiment.read(path);result['protocol_sha256']='changed'
    path.write_text(json.dumps(result),encoding='utf-8')
    with pytest.raises(AssertionError):experiment.answer(root)
    assert len(calls)==40
