"""Read-only retrieval comparison. Run: python -m evaluation.evaluate --output PATH."""
import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from langchain_community.embeddings import DashScopeEmbeddings

from src import config
from src.crud.knowledge import scoped_chunks
from src.services.corpus import KNOWLEDGE_BASE, load_internal_files
from src.services.retrieval import InternalKnowledgeRetriever, as_documents


class TimedRetriever(InternalKnowledgeRetriever):
    def _vector_search(self, query, hashes):
        start = time.perf_counter()
        result = super()._vector_search(query, hashes)
        self.vector_ms = (time.perf_counter() - start) * 1000
        return result

    def _keyword_search(self, query, hashes):
        start = time.perf_counter()
        result = super()._keyword_search(query, hashes)
        self.keyword_ms = (time.perf_counter() - start) * 1000
        return result


def metrics(ranking, relevant, k):
    ids = [document.id for document in ranking[:k]]
    hits = relevant.intersection(ids)
    return {"hit": bool(hits), "recall": len(hits) / len(relevant),
            "reciprocal_rank": next((1 / rank for rank, key in enumerate(ids, 1)
                                     if key in relevant), 0.0)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; preserve previous evaluation evidence")
    dataset_path = Path(__file__).with_name("questions.json")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    hashes = [file.document_hash for file in load_internal_files()]
    corpus = as_documents(scoped_chunks(hashes, KNOWLEDGE_BASE))
    labels = {}
    for question in dataset["questions"]:
        relevant = {document.id for document in corpus
                    if document.metadata.get("source") == question["source"]
                    and question["evidence"] in document.page_content}
        if not relevant:
            raise ValueError(f"No current chunk contains evidence for {question['id']}")
        labels[question["id"]] = relevant
    retriever = TimedRetriever(DashScopeEmbeddings(model=config.embedding_model_name))
    rows = []
    for question in dataset["questions"]:
        start = time.perf_counter()
        rankings = retriever.rankings(question["query"])
        elapsed_ms = (time.perf_counter() - start) * 1000
        relevant = labels[question["id"]]
        rows.append({"id": question["id"], "category": question["category"],
                     "query": question["query"], "labeled_chunk_ids": sorted(relevant),
                     "vector_ms": retriever.vector_ms, "keyword_ms": retriever.keyword_ms,
                     "hybrid_total_ms": elapsed_ms,
                     "modes": {mode: {"at_4": metrics(ranking, relevant, 4),
                                      "candidates": metrics(ranking, relevant, len(ranking)),
                                      "chunk_ids": [d.id for d in ranking],
                                      "sources": [{"filename": d.metadata.get("source"),
                                                   "chunk_index": d.metadata.get("chunk_index")}
                                                  for d in ranking[:4]]}
                               for mode, ranking in rankings.items()}})
    summary = {}
    for mode in ("vector", "keyword", "hybrid"):
        summary[mode] = {name + "_at_4": statistics.mean(
            float(row["modes"][mode]["at_4"][name]) for row in rows)
            for name in ("hit", "recall", "reciprocal_rank")}
        summary[mode]["candidate_hit"] = statistics.mean(
            float(row["modes"][mode]["candidates"]["hit"]) for row in rows)
    improved = [r["id"] for r in rows if r["modes"]["hybrid"]["at_4"]["reciprocal_rank"]
                > r["modes"]["vector"]["at_4"]["reciprocal_rank"]]
    regressed = [r["id"] for r in rows if r["modes"]["hybrid"]["at_4"]["reciprocal_rank"]
                 < r["modes"]["vector"]["at_4"]["reciprocal_rank"]]
    report = {"dataset_version": dataset["version"],
              "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
              "corpus_documents": len(hashes), "corpus_chunks": len(corpus),
              "parameters": {"candidate_k": config.retrieval_candidate_k,
                             "final_k": config.retrieval_top_k, "rrf_k": config.retrieval_rrf_k},
              "limitations": "Project-authored seed labels, 3/5 files covered; non-exhaustive relevance. No LLM answer-quality or product correctness evaluation. Timing includes embedding/network and first BM25 initialization; one sequential pass, not a load benchmark.",
              "summary": summary, "improved_rr": improved, "regressed_rr": regressed,
              "timing_ms": {key: {"median": statistics.median(row[key] for row in rows),
                                   "max": max(row[key] for row in rows)}
                            for key in ("vector_ms", "keyword_ms", "hybrid_total_ms")},
              "questions": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "questions"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
