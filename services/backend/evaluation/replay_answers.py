"""Replay frozen generations through RagService with all network access blocked."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import tarfile
from unittest.mock import patch


def replay(archive_path):
    from langchain_core.chat_history import InMemoryChatMessageHistory
    from langchain_core.documents import Document
    from langchain_core.runnables import RunnableLambda
    from src.services.context import EvidenceContextBuilder
    from src.services.corpus import load_internal_files
    from src.services.rag import RagService

    repo = Path(__file__).resolve().parents[3]
    with tarfile.open(archive_path) as archive:
        manifest = json.load(archive.extractfile("artifact-manifest.json"))

        def read(name):
            raw = archive.extractfile(name).read()
            assert hashlib.sha256(raw).hexdigest() == manifest[name], name
            return json.loads(raw)

        data = read("dataset.json")
        corpus = {row["id"]: row for row in read("corpus.json")}
        rows = []

        def deny_network(*args, **kwargs):
            raise AssertionError("Offline replay forbids network requests")

        with patch.object(socket.socket, "connect", deny_network), \
                patch.object(socket.socket, "connect_ex", deny_network), \
                patch.object(socket, "create_connection", deny_network):
            for q in data["questions"]:
                old = read(f"answers/{q['id']}-new.json")
                frozen = read(f"messages/{q['id']}-new.json")
                docs = [Document(id=key, page_content=corpus[key]["content"],
                                 metadata=corpus[key]["metadata"]) for key in q["frozen_chunk_ids"]]
                captured = []

                class Retriever:
                    def invoke(self, query):
                        assert query == q["query"]
                        return docs

                def model(value):
                    captured.extend({"role": m.type, "content": m.content} for m in value.to_messages())
                    return old["raw_generation"]

                history = InMemoryChatMessageHistory()
                service = RagService(Retriever(), RunnableLambda(model), lambda _: history,
                    context_entries_enabled=True,
                    context_builder=EvidenceContextBuilder(lambda: load_internal_files(repo / "knowledge/robot")))
                events = list(service.stream_answer(q["query"], "offline-" + q["id"]))
                answer = "".join(e.get("content", "") for e in events)
                assert captured == frozen["messages"], (q["id"], "model messages changed")
                assert events[0]["sources"] == old["sources"], (q["id"], "sources changed")
                assert history.messages[-1].content == answer, (q["id"], "history differs")
                rows.append({"id":q["id"], "query":q["query"], "risk":q["safety_expected"],
                             "before":old["answer"], "after":answer, "changed":answer != old["answer"]})
    return {"questions":len(rows), "network":"blocked", "paid_calls":0,
            "changed_ids":[r["id"] for r in rows if r["changed"]],
            "risk_changed_ids":[r["id"] for r in rows if r["risk"] and r["changed"]],
            "model_input_parity":len(rows), "source_parity":len(rows),
            "history_parity":len(rows), "per_question":rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = replay(args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({k:v for k,v in result.items() if k != "per_question"}))
