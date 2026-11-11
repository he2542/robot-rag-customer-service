"""Read-only retrieval comparison. Run: python -m evaluation.evaluate --output PATH."""
import argparse
import hashlib
import json
import statistics
import time
from collections import Counter
from pathlib import Path

from langchain_community.embeddings import DashScopeEmbeddings

from src import config
from src.crud.knowledge import scoped_chunks
from src.services.corpus import KNOWLEDGE_BASE, load_internal_files
from src.services.retrieval import InternalKnowledgeRetriever, as_documents
from src.services.rerank import Reranker


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
    parser.add_argument("--rerank", action="store_true", help="Compare model reranking on identical RRF candidates; incurs API usage")
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
    reranker = Reranker() if args.rerank else None
    rows = []
    for question in dataset["questions"]:
        start = time.perf_counter()
        rankings = retriever.rankings(question["query"])
        elapsed_ms = (time.perf_counter() - start) * 1000
        rerank_result = reranker.rerank(question["query"], rankings["hybrid"]) if reranker else None
        if rerank_result is not None:
            rankings["hybrid_rerank"] = rerank_result.documents
        relevant = labels[question["id"]]
        rows.append({"id": question["id"], "category": question["category"],
                     "query": question["query"], "labeled_chunk_ids": sorted(relevant),
                     "vector_ms": retriever.vector_ms, "keyword_ms": retriever.keyword_ms,
                     "hybrid_total_ms": elapsed_ms,
                     **({"rerank": rerank_result.diagnostics(), "rerank_ms": rerank_result.elapsed_ms,
                         "hybrid_with_rerank_ms": elapsed_ms + rerank_result.elapsed_ms}
                        if rerank_result is not None else {}),
                     "modes": {mode: {"at_4": metrics(ranking, relevant, 4),
                                      "candidates": metrics(ranking, relevant, len(ranking)),
                                      "chunk_ids": [d.id for d in ranking],
                                      "sources": [{"filename": d.metadata.get("source"),
                                                   "chunk_index": d.metadata.get("chunk_index")}
                                                  for d in ranking[:4]]}
                               for mode, ranking in rankings.items()}})
    summary = {}
    for mode in rows[0]["modes"]:
        summary[mode] = {name + "_at_4": statistics.mean(
            float(row["modes"][mode]["at_4"][name]) for row in rows)
            for name in ("hit", "recall", "reciprocal_rank")}
        summary[mode]["candidate_hit"] = statistics.mean(
            float(row["modes"][mode]["candidates"]["hit"]) for row in rows)
    improved = [r["id"] for r in rows if r["modes"]["hybrid"]["at_4"]["reciprocal_rank"]
                > r["modes"]["vector"]["at_4"]["reciprocal_rank"]]
    regressed = [r["id"] for r in rows if r["modes"]["hybrid"]["at_4"]["reciprocal_rank"]
                 < r["modes"]["vector"]["at_4"]["reciprocal_rank"]]
    rerank_summary = {}
    if args.rerank:
        rerank_summary = {
            "model": config.rerank_model,
            "status_counts": dict(Counter(row["rerank"]["status"] for row in rows)),
            "fallback_reasons": dict(Counter(row["rerank"]["reason"] for row in rows if row["rerank"]["status"] == "fallback")),
            "reported_usage_tokens": sum(row["rerank"]["usage_tokens"] or 0 for row in rows),
            "usage_unknown_count": sum(row["rerank"]["usage_tokens"] is None for row in rows),
            "improved_rr": [r["id"] for r in rows if r["modes"]["hybrid_rerank"]["at_4"]["reciprocal_rank"] > r["modes"]["hybrid"]["at_4"]["reciprocal_rank"]],
            "regressed_rr": [r["id"] for r in rows if r["modes"]["hybrid_rerank"]["at_4"]["reciprocal_rank"] < r["modes"]["hybrid"]["at_4"]["reciprocal_rank"]],
            "lost_hits": [r["id"] for r in rows if r["modes"]["hybrid"]["at_4"]["hit"] and not r["modes"]["hybrid_rerank"]["at_4"]["hit"]],
        }
    report = {"dataset_version": dataset["version"],
              "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
              "corpus_documents": len(hashes), "corpus_chunks": len(corpus),
              "parameters": {"candidate_k": config.retrieval_candidate_k,
                             "final_k": config.retrieval_top_k, "rrf_k": config.retrieval_rrf_k},
              "limitations": "Project-authored seed labels, 3/5 files covered; non-exhaustive relevance. No LLM answer-quality or product correctness evaluation. Timing includes embedding/network and first BM25 initialization; one sequential pass, not a load benchmark.",
              "summary": summary, "improved_rr": improved, "regressed_rr": regressed,
              **({"rerank": rerank_summary} if args.rerank else {}),
              "timing_ms": {key: {"median": statistics.median(row[key] for row in rows),
                                   "max": max(row[key] for row in rows)}
                            for key in (["vector_ms", "keyword_ms", "hybrid_total_ms"] +
                                        (["rerank_ms", "hybrid_with_rerank_ms"] if args.rerank else []))},
              "questions": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "questions"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
