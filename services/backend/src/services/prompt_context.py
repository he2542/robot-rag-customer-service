"""Deterministic evidence selection and serialized UTF-8 input budgets."""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import json
import math
import re

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from .context import _merge_spans
from .keyword import tokenize


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def byte_size(value):
    return len(encode(value).encode("utf-8"))


def source_items(documents):
    items = []
    for index, document in enumerate(documents, 1):
        item = {"id": f"S{index}", "filename": str(document.metadata.get("source", "内置资料")),
                "chunk_index": document.metadata.get("chunk_index", 0), "excerpt": document.page_content}
        digest, spans = document.metadata.get("document_hash"), document.metadata.get("source_spans")
        if (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                and isinstance(spans, list) and spans
                and all(isinstance(s, dict) and type(s.get("start_line")) is int
                        and type(s.get("end_line")) is int and 1 <= s["start_line"] <= s["end_line"] for s in spans)):
            item["document_hash"] = digest
            item["source_spans"] = [{"start_line": s["start_line"], "end_line": s["end_line"]} for s in spans]
        items.append(item)
    return items


@dataclass(frozen=True)
class ContextLimits:
    total: int = 32 * 1024
    evidence: int = 12 * 1024
    history: int = 8 * 1024

    def __post_init__(self):
        if any(type(x) is not int or x < 0 for x in (self.total, self.evidence, self.history)):
            raise ValueError("Context byte limits must be nonnegative integers")


@dataclass(frozen=True)
class PackedEvidence:
    documents: tuple[Document, ...]
    duplicates: int
    dropped_units: int
    evidence_bytes: int


@lru_cache(maxsize=1024)
def _terms(text):
    return frozenset(tokenize(text))


def _assemble(documents, units):
    grouped = {}
    for doc_index, unit_index, unit in units:
        grouped.setdefault(doc_index, []).append((unit_index, unit))
    packed = []
    for doc_index, selected in sorted(grouped.items()):
        original = documents[doc_index]
        text = original.metadata.get("_context_text")
        if text is None:
            packed.append(original)
            continue
        spans = _merge_spans(text, [span for _, unit in selected for span in unit["spans"]])
        metadata = {k: v for k, v in original.metadata.items() if not k.startswith("_context_")}
        metadata["source_spans"] = [{"start_line": text.count("\n", 0, left) + 1,
                                     "end_line": text.count("\n", 0, right - 1) + 1} for left, right in spans]
        packed.append(Document(id=original.id, metadata=metadata,
                               page_content="\n\n".join(text[a:b] for a, b in spans)))
    return packed


def pack_evidence(documents, question, limit):
    """Deduplicate exact text including its conditions; omit whole units to fit."""
    units, seen, duplicates = [], set(), 0
    for i, doc in enumerate(documents):
        for j, unit in enumerate(doc.metadata.get("_context_units", [{"text": doc.page_content}])):
            # A different file/version may encode applicability in its name.
            key = (doc.metadata.get("source"), doc.metadata.get("document_hash"), unit["text"].strip())
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            units.append((i, j, unit))
    terms = _terms(question)
    frequency = Counter(term for _, _, unit in units for term in _terms(unit["text"]))

    def rank(row):
        i, j, unit = row
        words = _terms(unit["text"])
        score = sum(1 + math.log((len(units) + 1) / (frequency[t] + 1)) for t in terms & words)
        # Query match in a question/phenomenon line is stronger than a passing mention.
        lines = [line for line in unit["text"].splitlines() if not line.startswith("#")]
        score += 2 * len(terms & _terms(next((line for line in lines if re.match(r"\d+\.", line)), "")))
        return (-score, i, j)

    chosen = []
    for row in sorted(units, key=rank):
        candidate = _assemble(documents, [*chosen, row])
        if byte_size(source_items(candidate)) <= limit:
            chosen.append(row)
    packed = _assemble(documents, chosen)
    return PackedEvidence(tuple(packed), duplicates, len(units) - len(chosen), byte_size(source_items(packed)))


def _wire_messages(system, history, payload):
    roles = {"human": "user", "ai": "assistant"}
    return [{"role": "system", "content": system},
            *[{"role": roles[m.type], "content": m.content} for m in history],
            {"role": "user", "content": encode(payload)}]


def recent_turns(messages, limit):
    """Retain a contiguous suffix of complete user/assistant pairs, verbatim."""
    pairs, pending = [], None
    for message in messages:
        if message.type == "human" and isinstance(message.content, str):
            pending = message
        elif message.type == "ai" and isinstance(message.content, str) and pending is not None:
            # Only content and native role enter the prompt; historical metadata,
            # names and tool payloads cannot bypass the serialized-byte budget.
            pairs.append((HumanMessage(pending.content), AIMessage(message.content)))
            pending = None
        else:
            pending = None
    selected = []
    for pair in reversed(pairs):
        candidate = [*pair, *selected]
        wire = [{"role": "user" if m.type == "human" else "assistant", "content": m.content} for m in candidate]
        if byte_size(wire) > limit:
            break
        selected = candidate
    return selected


class PromptContextBuilder:
    def __init__(self, system, limits=ContextLimits()):
        self.system, self.limits = system, limits

    def evidence(self, question, documents):
        fixed = byte_size(_wire_messages(self.system, [], {"question": question, "references": []}))
        # Escaping the nested JSON reference payload can cost twice its own bytes.
        available = min(self.limits.evidence, max(0, (self.limits.total - fixed) // 2))
        result = pack_evidence(documents, question, available)
        while result.documents and byte_size(_wire_messages(self.system, [], {
                "question": question, "references": source_items(result.documents)})) > self.limits.total:
            available = max(0, available - 256)
            result = pack_evidence(documents, question, available)
        return result

    def messages(self, question, documents, history):
        payload = {"question": question, "references": source_items(documents)}
        selected = recent_turns(history, self.limits.history)
        while selected and byte_size(_wire_messages(self.system, selected, payload)) > self.limits.total:
            selected = selected[2:]
        total = byte_size(_wire_messages(self.system, selected, payload))
        if total > self.limits.total:
            raise ValueError("Current question and system rules exceed the context byte budget")
        diagnostic = {"input_bytes": total, "evidence_bytes": byte_size(payload["references"]),
                      "history_messages": len(selected), "history_dropped": len(history) - len(selected)}
        return {"history": selected, "request_payload": encode(payload)}, diagnostic
