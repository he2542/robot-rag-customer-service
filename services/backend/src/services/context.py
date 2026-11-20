"""Recover complete source entries from retrieved spans without model rewriting."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import re

from langchain_core.documents import Document

from .corpus import KnowledgeFile, load_internal_files
from .evidence_review import REVIEW_DECISIONS

_MARKER = re.compile(r"(?m)^(?:(?P<number>\d+)\.[ \t]+|(?P<heading>#{1,6})[ \t]+)")


@dataclass(frozen=True)
class Entry:
    start: int
    end: int
    start_line: int
    entry_hash: str
    prefix_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class EvidenceContext:
    documents: tuple[Document, ...]
    excluded_reviews: tuple[str, ...]
    fallback_reasons: tuple[str, ...]
    entry_count: int


def _trim_span(text, start, end):
    raw = text[start:end]
    start += len(raw) - len(raw.lstrip())
    return start, start + len(raw.strip())


@lru_cache(maxsize=16)
def source_entries(file: KnowledgeFile) -> tuple[Entry, ...]:
    """Keep headings and their applicability preambles with every selected entry."""
    text = file.text
    markers = list(_MARKER.finditer(text))
    if not markers:
        return ()
    preamble = _trim_span(text, 0, markers[0].start())
    base = (preamble,) if preamble[0] < preamble[1] else ()
    headings = []
    entries = []
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        span = _trim_span(text, marker.start(), end)
        if marker["heading"]:
            level = len(marker["heading"])
            headings = [(depth, region) for depth, region in headings if depth < level]
            headings.append((level, span))
            continue
        content = text[span[0]:span[1]]
        entries.append(Entry(
            span[0], span[1], text.count("\n", 0, span[0]) + 1,
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
            base + tuple(region for _, region in headings),
        ))
    return tuple(entries)


def _merge_spans(text, spans):
    merged = []
    for start, end in sorted(set(spans)):
        if merged and (start <= merged[-1][1] or not text[merged[-1][1]:start].strip()):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class EvidenceContextBuilder:
    def __init__(self, files_loader=load_internal_files, reviews=REVIEW_DECISIONS):
        self.files_loader = files_loader
        self.reviews = {(r.filename, r.document_hash, r.start_line, r.entry_hash): r.id for r in reviews}

    def build(self, documents: list[Document]) -> EvidenceContext:
        if not documents:
            return EvidenceContext((), (), (), 0)
        files = {file.filename: file for file in self.files_loader()}
        prepared, excluded, fallbacks = [], set(), []
        entry_count = 0
        for document in documents:
            if not document.page_content.strip():
                continue
            file = files.get(document.metadata.get("source"))
            if file is None or document.metadata.get("document_hash") != file.document_hash:
                prepared.append(document)
                fallbacks.append("unverified_source_version")
                continue
            start = file.text.find(document.page_content)
            if start < 0 or file.text.find(document.page_content, start + 1) >= 0:
                prepared.append(document)
                fallbacks.append("ambiguous_source_span")
                continue
            end = start + len(document.page_content)
            entries = [entry for entry in source_entries(file) if entry.start < end and entry.end > start]
            if not entries:
                prepared.append(document)
                fallbacks.append("unstructured_span")
                continue
            spans, units = [], []
            for entry in entries:
                review = self.reviews.get((file.filename, file.document_hash, entry.start_line, entry.entry_hash))
                if review:
                    excluded.add(review)
                else:
                    spans.extend((*entry.prefix_spans, (entry.start, entry.end)))
                    units.append({"spans": [*entry.prefix_spans, (entry.start, entry.end)],
                                  "text": "\n\n".join(file.text[a:b] for a, b in
                                                        (*entry.prefix_spans, (entry.start, entry.end)))})
                    entry_count += 1
            if not spans:
                continue
            spans = _merge_spans(file.text, spans)
            excerpt = "\n\n".join(file.text[left:right] for left, right in spans)
            metadata = dict(document.metadata)
            # Selection-only data never enters source_items() or the model.
            metadata["_context_units"] = units
            metadata["_context_text"] = file.text
            metadata["source_spans"] = [
                {"start_line": file.text.count("\n", 0, left) + 1,
                 "end_line": file.text.count("\n", 0, right - 1) + 1}
                for left, right in spans
            ]
            prepared.append(Document(id=document.id, page_content=excerpt, metadata=metadata))
        return EvidenceContext(tuple(prepared), tuple(sorted(excluded)), tuple(fallbacks), entry_count)
