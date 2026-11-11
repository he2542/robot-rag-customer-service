"""Reproduce aggregate metrics from frozen checkpoint evidence, no API calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics

from evaluation.benchmark import read, write_new, checked_dataset, digest
from evaluation.paired_statistics import paired_binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    questions = checked_dataset(root)
    retrieval = {q["id"]: read(root / "retrieval" / (q["id"] + ".json")) for q in questions}
    judgments = {q["id"]: read(root / "judgments" / (q["id"] + ".json")) for q in questions}
    for q in questions:
        records = [retrieval[q["id"]], judgments[q["id"]]] + [
            read(root / "answers" / (q["id"] + "-" + arm + ".json"))
            for arm in ("hybrid", "hybrid_rerank")]
        if any(record["dataset_sha256"] != digest(root / "dataset.json") for record in records):
            raise ValueError("Checkpoint digest mismatch")

    def comparison(metric, subset=questions):
        rows = []
        for q in subset:
            values = []
            for arm in ("hybrid", "hybrid_rerank"):
                if metric == "hit":
                    value = bool(set(q["labeled_chunk_ids"]) & set(retrieval[q["id"]]["rankings"][arm][:4]))
                else:
                    score = judgments[q["id"]]["scores"][arm]
                    value = (score["correct"] and score["supported"] if metric == "grounded_correct"
                             else score[metric])
                values.append(value)
            rows.append({"source": q["source"], "cluster": q["cluster"],
                         "before": values[0], "after": values[1]})
        return paired_binary(rows)

    result = {"dataset_sha256": digest(root / "dataset.json"), "n": len(questions),
              "primary": {m: comparison(m) for m in ("hit", "grounded_correct")},
              "secondary": {m: comparison(m) for m in ("correct", "supported", "context_sufficient")},
              "by_source": {source: {m: comparison(m, [q for q in questions if q["source"] == source])
                                      for m in ("hit", "grounded_correct")}
                            for source in sorted({q["source"] for q in questions})}}
    result["retrieval_modes"] = {}
    for arm in ("vector", "keyword", "hybrid", "hybrid_rerank"):
        hits, recalls, rrs, candidates = [], [], [], []
        for q in questions:
            ids = retrieval[q["id"]]["rankings"][arm]
            relevant = set(q["labeled_chunk_ids"])
            hits.append(bool(relevant.intersection(ids[:4])))
            candidates.append(bool(relevant.intersection(ids)))
            recalls.append(len(relevant.intersection(ids[:4])) / len(relevant))
            rrs.append(next((1 / i for i, key in enumerate(ids[:4], 1) if key in relevant), 0))
        result["retrieval_modes"][arm] = {"hit_at_4": statistics.mean(hits), "recall_at_4": statistics.mean(recalls),
                                           "mrr_at_4": statistics.mean(rrs), "candidate_hit": statistics.mean(candidates)}
    invalid = [q["id"] for q in questions if not judgments[q["id"]]["reference_valid"]]
    result["ordinary_items_only"] = {m: comparison(m, [q for q in questions if not q["safety_expected"]]) for m in ("hit", "grounded_correct")}
    result["safety_items_only"] = {m: comparison(m, [q for q in questions if q["safety_expected"]]) for m in ("hit", "grounded_correct")}
    result["reference_invalid_ids"] = invalid
    if invalid:
        result["reference_valid_only_sensitivity"] = comparison("grounded_correct", [q for q in questions if q["id"] not in invalid])
    result["rerank_status"] = dict(Counter(r["rerank"]["status"] for r in retrieval.values()))
    result["rerank_reasons"] = dict(Counter(r["rerank"]["reason"] for r in retrieval.values() if r["rerank"]["status"] != "success"))
    result["usage"] = {"rerank_reported_tokens": sum(r["rerank"]["usage_tokens"] or 0 for r in retrieval.values()),
                       "question_generation": {key: sum(read(p)["usage"].get(key, 0) for p in (root / "generation").glob("*.json"))
                                               for key in ("input_tokens", "output_tokens", "total_tokens")},
                       "judge": {key: sum(j["usage"].get(key, 0) for j in judgments.values()) for key in ("input_tokens", "output_tokens", "total_tokens")},
                       "reference_validation": {key: sum(read(p)["usage"].get(key, 0) for p in (root / "validation").glob("*.json")) for key in ("input_tokens", "output_tokens", "total_tokens")},
                       "swapped_judge": {key: sum(read(p)["usage"].get(key, 0) for p in (root / "judge_swapped").glob("*.json")) for key in ("input_tokens", "output_tokens", "total_tokens")},
                       "answers": "Streaming token usage and failed/cancelled attempts not fully collected; not a complete cost accounting"}
    timings = {"rerank": [r["rerank"]["elapsed_ms"] for r in retrieval.values()],
               "hybrid_retrieval": [r["hybrid_ms"] for r in retrieval.values()]}
    result["timing_ms"] = {key: {"median": statistics.median(values), "p95_observed": sorted(values)[int(.95 * (len(values) - 1))],
                                       "max": max(values)} for key, values in timings.items()}
    swaps = [read(p) for p in sorted((root / "judge_swapped").glob("*.json"))]
    if swaps:
        disagreements = []
        swap_map = {r["id"]: r for r in swaps}
        for row in swaps:
            for arm in ("hybrid", "hybrid_rerank"):
                first, second = judgments[row["id"]]["scores"][arm], row["scores"][arm]
                if (first["correct"] and first["supported"]) != (second["correct"] and second["supported"]):
                    disagreements.append({"id": row["id"], "arm": arm})
        result["swapped_order_audit"] = {"pairs": len(swaps), "answer_decisions": len(swaps) * 2,
                                         "disagreements": disagreements, "agreement_rate": 1 - len(disagreements) / (2 * len(swaps))}
        if len(swaps) == len(questions):
            for label, combine in (("swapped_only", lambda a, b: b),
                                   ("both_orders_pass", lambda a, b: a and b),
                                   ("either_order_pass", lambda a, b: a or b)):
                rows = []
                for q in questions:
                    values = []
                    for arm in ("hybrid", "hybrid_rerank"):
                        first = judgments[q["id"]]["scores"][arm]
                        second = swap_map[q["id"]]["scores"][arm]
                        values.append(combine(first["correct"] and first["supported"],
                                              second["correct"] and second["supported"]))
                    rows.append({"source": q["source"], "cluster": q["cluster"],
                                 "before": values[0], "after": values[1]})
                result["swapped_order_audit"][label] = paired_binary(rows)
            result["swapped_order_audit"]["disagreements_by_arm"] = dict(Counter(d["arm"] for d in disagreements))
    files = sorted(p for p in root.rglob("*.json") if p != args.output)
    result["evidence_sha256"] = {p.relative_to(root).as_posix(): digest(p) for p in files}
    write_new(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"evidence_sha256", "by_source"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
