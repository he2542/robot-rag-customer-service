"""Frozen small paired prompt experiment; prepare/validate are offline."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import socket
import subprocess
import tarfile
import time
from unittest.mock import patch

from evaluation.budget import BudgetError, add_budget_arguments, budget_from_args, require_budget

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
CASE_IDS = ("b022 b030 b038 b044 b074 b090 b099 b106 b126 b136 b157 b160 "
            "b187 b196 b215 b233 b252 b260 b280 b295").split()
RISK_IDS = {"b022","b090","b126","b196","b215","b233"}
REVIEW_POINTS = {
    "b030":["区分机型是否支持、功能是否开启等适用条件", "地毯识别或打滑原因有本轮证据，不强求过薄或过厚某一种说法"],
    "b044":["指出本轮证据支持的长毛地毯缠绕/适配原因", "提供与所述原因对应的处理建议，保留已满足条件"],
    "b074":["说明本轮证据支持的水印原因", "给出对应处理建议，不把干拖等同降低速度"],
    "b090":["先停止异常操作，内部电机/轴承交给售后", "有附件证据则说明；证据不足可澄清，不补出已排除的润滑步骤"],
    "b099":["区分集尘袋、拖布、滤网的清洗/更换", "维护周期及条件有本轮证据，差异不合并为统一周期"],
    "b126":["停止使用/充电并联系专业售后", "说明有证据的潜在问题，检查角色清楚，不要求用户拆修"],
    "b187":["列出本轮证据支持的使用限制并保留数值或条件", "不将课程通用限制推广为所有机型事实"],
    "b196":["停止异常运行，避免强行继续使用", "常规清理有证据，内部电机/轴承处理交售后，不自行润滑"],
    "b260":["说明课程选购建议中的智能家居联动能力及例子", "不在型号未知时断言用户设备必然支持"],
    "b295":["说明课程建议的过热/过载保护及使用条件", "区分功能咨询与已经发生的过热故障"],
}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")


def extract_prompt(source):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(isinstance(t,ast.Name) and t.id=="CONTEXT_SYSTEM_PROMPT" for t in node.targets):
            value=ast.literal_eval(node.value)
            if isinstance(value,str):return value
    raise ValueError("No literal context prompt")


def serialize(messages):
    return [{"role":m.type,"content":m.content} for m in messages]


def build(q, corpus, system, model):
    from langchain_core.chat_history import InMemoryChatMessageHistory
    from langchain_core.documents import Document
    from src.services.context import EvidenceContextBuilder
    from src.services.corpus import load_internal_files
    from src.services.rag import RagService
    class FrozenRetriever:
        def invoke(self, query):
            assert query==q["query"]
            return [Document(id=k,page_content=corpus[k]["content"],metadata=corpus[k]["metadata"])
                    for k in q["frozen_chunk_ids"]]
    history=InMemoryChatMessageHistory()
    service=RagService(FrozenRetriever(),model,lambda _:history,context_entries_enabled=True,
        context_system_prompt=system,
        context_builder=EvidenceContextBuilder(lambda:load_internal_files(REPO/"knowledge/robot")))
    return service,history


def capture(q, corpus, system):
    from langchain_core.runnables import RunnableLambda
    captured=[]
    def model(value):
        captured.extend(serialize(value.to_messages()))
        return '{"decision":"insufficient","claims":[],"question":""}'
    service,history=build(q,corpus,system,RunnableLambda(model))
    events=list(service.stream_answer(q["query"],"capture"))
    assert len(captured)==2 and history.messages[0].content==q["query"]
    assert history.messages[-1].content=="".join(e.get("content","") for e in events)
    assert json.loads(captured[-1]["content"])["references"]==events[0]["sources"]
    return {"messages":captured,"sources":events[0]["sources"]}


def source_hashes():
    files=[BACKEND/"src/services"/name for name in ["rag.py","prompts.py","context.py","answer_policy.py","prompt_context.py","evidence_review.py"]]
    files.extend([Path(__file__),BACKEND/"evaluation/budget.py"])
    files.extend((REPO/"knowledge/robot").glob("*.txt"))
    return {p.relative_to(REPO).as_posix():digest(p) for p in files}


def prepare(root, archive_path, baseline_ref):
    from src.services.prompts import CONTEXT_SYSTEM_PROMPT
    if root.exists():raise FileExistsError(root)
    if not baseline_ref or any(c not in "0123456789abcdef" for c in baseline_ref):
        raise ValueError("Baseline must be a commit hash")
    source=subprocess.check_output(["git","show",f"{baseline_ref}:services/backend/src/services/prompts.py"],cwd=REPO).decode("utf-8")
    systems={"baseline":extract_prompt(source),"optimized":CONTEXT_SYSTEM_PROMPT}
    if systems["baseline"]==systems["optimized"]:raise ValueError("Prompts are identical")
    with tarfile.open(archive_path) as archive:
        manifest=json.load(archive.extractfile("artifact-manifest.json"))
        def member(name):
            raw=archive.extractfile(name).read()
            assert hashlib.sha256(raw).hexdigest()==manifest[name],name
            return json.loads(raw)
        data=member("dataset.json")
        corpus_rows=member("corpus.json");corpus={r["id"]:r for r in corpus_rows}
        questions=[{**q,"review_points":REVIEW_POINTS.get(q["id"],q["required_points"]),
                    "review_risk":q["id"] in RISK_IDS} for q in data["questions"] if q["id"] in CASE_IDS]
        assert len(questions)==20 and len({q["source"] for q in questions})==5
        messages={}
        def deny(*a,**kw):raise AssertionError("Offline preparation forbids network")
        with patch.object(socket.socket,"connect",deny),patch.object(socket.socket,"connect_ex",deny):
            for q in questions:
                for arm,system in systems.items():messages[f"{q['id']}-{arm}"]=capture(q,corpus,system)
                a,b=(messages[f"{q['id']}-{arm}"] for arm in systems)
                assert a["sources"]==b["sources"],q["id"]
                assert a["messages"]==member(f"messages/{q['id']}-new.json")["messages"],q["id"]
                for arm in systems:
                    assert len(json.dumps(messages[f"{q['id']}-{arm}"]["messages"],ensure_ascii=False).encode())<=25*1024
    root.mkdir(parents=True)
    jobs=[{"id":q["id"],"arms":["baseline","optimized"] if i%2==0 else ["optimized","baseline"]}
          for i,q in enumerate(questions)]
    random.Random(20261120).shuffle(jobs)
    write(root/"dataset.json",{"version":"intent-workflow-20-v1","questions":questions,"parent_archive_sha256":digest(archive_path)})
    write(root/"corpus.json",corpus_rows);write(root/"prompts.json",systems)
    write(root/"protocol.json",{"baseline_commit":baseline_ref,"model":"qwen-plus","temperature":0,
        "seed":20261111,"max_tokens":1024,"enable_thinking":False,"execution":jobs,
        "factor":"system workflow only; same candidates, source construction, output policy and independent empty history",
        "review":"Frozen question-level points; inspect raw claims and visible answers separately; no paid judge",
        "budget_proposal":{"max_attempts":40,"estimated_cny_cap":"1.00"}})
    for key,value in messages.items():write(root/"messages"/(key+".json"),value)
    write(root/"source-hashes.json",source_hashes())
    inputs={p.relative_to(root).as_posix():digest(p) for p in root.rglob("*.json")}
    write(root/"inputs-manifest.json",inputs)
    return {"questions":20,"prepared_messages":40,"source_parity":20,"baseline_original_messages":20,"paid_calls":0}


def checked(root):
    for name,expected in read(root/"inputs-manifest.json").items():
        assert digest(root/name)==expected,name
    assert read(root/"source-hashes.json")==source_hashes(),"Source changed after preparation"
    return read(root/"dataset.json"),read(root/"protocol.json"),read(root/"prompts.json")


def answer(root):
    require_budget()
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_community.chat_models.tongyi import ChatTongyi
    data,protocol,systems=checked(root)
    questions={q["id"]:q for q in data["questions"]}
    corpus={r["id"]:r for r in read(root/"corpus.json")}
    for job in protocol["execution"]:
        q=questions[job["id"]]
        for arm in job["arms"]:
            path=root/"answers"/f"{q['id']}-{arm}.json"
            expected=read(root/"messages"/path.name)
            if path.exists():
                old=read(path)
                assert old["message_sha256"]==digest(root/"messages"/path.name)
                assert old["dataset_sha256"]==digest(root/"dataset.json")
                assert old["protocol_sha256"]==digest(root/"protocol.json")
                continue
            class Trace(BaseCallbackHandler):
                raise_error=True
                raw=None
                info=None
                def on_chat_model_start(self,serialized,messages,**kw):
                    assert serialize(messages[0])==expected["messages"],"Actual model input changed"
                def on_llm_end(self,response,**kw):
                    generation=response.generations[0][0]
                    self.raw,self.info=generation.text,generation.generation_info
            trace=Trace()
            model=ChatTongyi(model=protocol["model"],max_retries=1,callbacks=[trace],model_kwargs={
                "enable_thinking":False,"max_tokens":protocol["max_tokens"],"temperature":0,"seed":protocol["seed"]})
            service,history=build(q,corpus,systems[arm],model)
            start=time.perf_counter()
            try:
                events=list(service.stream_answer(q["query"],q["id"]+arm))
            except Exception as error:
                write(root/"failures"/f"{q['id']}-{arm}-{time.time_ns()}.json",{
                    "id":q["id"],"arm":arm,"error_type":type(error).__name__,
                    "message_sha256":digest(root/"messages"/path.name)})
                raise
            text="".join(e.get("content","") for e in events)
            assert events[0]["sources"]==expected["sources"]
            assert history.messages[-1].content==text and trace.raw is not None
            write(path,{"id":q["id"],"arm":arm,"answer":text,"raw_generation":trace.raw,
                "generation_info":trace.info,"sources":events[0]["sources"],"elapsed_ms":(time.perf_counter()-start)*1000,
                "created_at":datetime.now(timezone.utc).isoformat(),"message_sha256":digest(root/"messages"/path.name),
                "dataset_sha256":digest(root/"dataset.json"),"protocol_sha256":digest(root/"protocol.json")})
            print(json.dumps({"answered":path.name}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=["prepare","validate","answer"])
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--archive",type=Path)
    parser.add_argument("--baseline-ref",default="3897dd4")
    add_budget_arguments(parser)
    args=parser.parse_args()
    if args.stage=="prepare":
        if args.archive is None:parser.error("prepare requires --archive")
        print(json.dumps(prepare(args.root,args.archive,args.baseline_ref)))
    elif args.stage=="validate":
        data,_,_=checked(args.root)
        print(json.dumps({"validated_questions":len(data["questions"]),"paid_calls":0}))
    else:
        try:
            with budget_from_args(args):answer(args.root)
        except BudgetError as error:parser.exit(2,str(error)+"\n")


if __name__=="__main__":main()
