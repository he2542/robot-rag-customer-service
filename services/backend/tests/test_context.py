"""Evidence fidelity, review scope and the actual model/SSE message boundary."""
import json

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
import pytest

from src.services.context import EvidenceContextBuilder, source_entries
from src.services.corpus import KnowledgeFile, internal_document_hash, load_internal_files
from src.services.evidence_review import REVIEW_DECISIONS, ReviewDecision
from src.services.rag import RagService, source_items


def file(text, name="资料.txt"):
    return KnowledgeFile(name, text, internal_document_hash(text, name))


def chunk(source, content, index=0):
    return Document(id=f"chunk-{index}", page_content=content, metadata={
        "source": source.filename, "document_hash": source.document_hash, "chunk_index": index,
    })


def review(source, number):
    entry = source_entries(source)[number]
    return ReviewDecision("test-review", source.filename, source.document_hash,
                          entry.start_line, entry.entry_hash, "Confirmed exclusion")


def test_reconstructs_complete_entries_and_keeps_conditions_numbers_and_negation():
    source = file("# 说明\n仅适用于A型号。\n1. 条件：温度≤35℃。\n不要在潮湿处使用。\n2. 其他事项。\n")
    original = chunk(source, "温度≤35℃。\n不要在潮湿处使")
    result = EvidenceContextBuilder(lambda: [source], ()).build([original])
    assert result.documents[0].page_content == source.text[:source.text.index("2.")].strip()
    assert result.documents[0].metadata["source_spans"] == [{"start_line": 1, "end_line": 4}]
    assert original.page_content == "温度≤35℃。\n不要在潮湿处使"


def test_exclusion_retains_neighbors_and_never_rejoins_across_the_removed_entry():
    source = file("1. 先检查滤网。\n2. 已审校排除的处理。\n3. 保留温度≤30℃且不得水洗。\n")
    result = EvidenceContextBuilder(lambda: [source], (review(source, 1),)).build([chunk(source, source.text.strip())])
    assert result.documents[0].page_content == "1. 先检查滤网。\n\n3. 保留温度≤30℃且不得水洗。"
    assert result.documents[0].metadata["source_spans"] == [
        {"start_line": 1, "end_line": 1}, {"start_line": 3, "end_line": 3},
    ]
    assert result.excluded_reviews == ("test-review",)


def test_repeated_numbers_in_distinct_sections_are_disambiguated_by_location():
    source = file("## A\n1. 相同条目。\n## B\n1. 相同条目。\n")
    result = EvidenceContextBuilder(lambda: [source], (review(source, 0),)).build([chunk(source, source.text.strip())])
    assert result.documents[0].page_content == "## B\n1. 相同条目。"
    assert result.documents[0].metadata["source_spans"] == [{"start_line": 3, "end_line": 4}]


def test_review_does_not_apply_to_new_version_or_different_filename():
    old = file("1. 已审校条目。\n")
    changed = file("1. 已审校条目。\n2. 新增条件。\n")
    renamed = file(old.text, "另一文件.txt")
    builder = EvidenceContextBuilder(lambda: [changed, renamed], (review(old, 0),))
    result = builder.build([chunk(changed, changed.text.strip()), chunk(renamed, renamed.text.strip())])
    assert len(result.documents) == 2 and not result.excluded_reviews


@pytest.mark.parametrize("source_text,content,reason", [
    ("说明\n同一段。\n同一段。", "同一段。", "ambiguous_source_span"),
    ("没有编号的完整段落。", "没有编号的完整段落。", "unstructured_span"),
    ("1. 文件正文。", "无法定位的正文。", "ambiguous_source_span"),
])
def test_unreliable_structure_preserves_the_original_chunk(source_text, content, reason):
    source = file(source_text)
    original = chunk(source, content)
    result = EvidenceContextBuilder(lambda: [source], ()).build([original])
    assert result.documents == (original,)
    assert result.fallback_reasons == (reason,)


def test_unknown_version_falls_back_without_claiming_source_positions():
    source = file("1. 文件正文。")
    original = chunk(source, source.text)
    original.metadata["document_hash"] = "outdated-version"
    result = EvidenceContextBuilder(lambda: [source], ()).build([original])
    assert result.documents == (original,) and "source_spans" not in result.documents[0].metadata
    assert result.fallback_reasons == ("unverified_source_version",)


def test_no_evidence_avoids_loading_source_files():
    def must_not_load():
        raise AssertionError("empty retrieval should not read files")
    assert not EvidenceContextBuilder(must_not_load).build([]).documents


def test_actual_review_decisions_match_current_source_versions_and_exact_entries():
    files = {source.filename: source for source in load_internal_files()}
    for decision in REVIEW_DECISIONS:
        source = files[decision.filename]
        assert source.document_hash == decision.document_hash
        matches = [entry for entry in source_entries(source)
                   if entry.start_line == decision.start_line and entry.entry_hash == decision.entry_hash]
        assert len(matches) == 1
        entry = matches[0]
        # Even a cut through the middle of a blocked entry cannot bypass review.
        fragment = source.text[entry.start + 8:entry.end - 3]
        result = EvidenceContextBuilder(lambda: [source]).build([chunk(source, fragment)])
        assert not result.documents and result.excluded_reviews == (decision.id,)


def test_model_and_sources_share_prepared_text_and_continuous_ids_after_exclusion():
    source = file("1. 审校排除。\n2. 必须先断电，温度≤35℃。\n")
    docs = [chunk(source, "1. 审校排除。", 0), chunk(source, "先断电，温度≤35℃", 1)]
    prompts = []
    history = InMemoryChatMessageHistory()

    class Retriever:
        def invoke(self, query):
            return docs

    def model(value):
        prompts.append(value.to_messages())
        return json.dumps({"decision": "answer", "claims": [
            {"text": "必须先断电，温度≤35℃。", "quote": "2. 必须先断电，温度≤35℃。"}]}, ensure_ascii=False)

    service = RagService(Retriever(), RunnableLambda(model), lambda _: history,
                         context_builder=EvidenceContextBuilder(lambda: [source], (review(source, 0),)),
                         context_entries_enabled=True)
    events = list(service.stream_answer("怎么处理？", "prepared"))
    sources = events[0]["sources"]
    assert len(sources) == 1 and sources[0]["id"] == "S1" and sources[0]["chunk_index"] == 1
    assert sources[0]["excerpt"] == "2. 必须先断电，温度≤35℃。"
    assert sources[0]["document_hash"] == source.document_hash
    assert sources[0]["source_spans"] == [{"start_line": 2, "end_line": 2}]
    payload = json.loads(prompts[0][-1].content)
    assert payload["references"] == sources and "审校排除" not in prompts[0][-1].content
    assert history.messages[0].content == "怎么处理？"
    assert "必须先断电，温度≤35℃。 [S1]" == "".join(event.get("content", "") for event in events)
    assert "S2" not in "".join(event.get("content", "") for event in events)


def test_all_excluded_refuses_without_model_call():
    source = file("1. 审校排除。")
    calls = []

    class Retriever:
        def invoke(self, query):
            return [chunk(source, source.text)]

    service = RagService(Retriever(), RunnableLambda(lambda v: calls.append(v) or "wrong"),
                         context_builder=EvidenceContextBuilder(lambda: [source], (review(source, 0),)),
                         context_entries_enabled=True)
    events = list(service.stream_answer("怎么处理？", "excluded"))
    assert events[0] == {"sources": []} and not calls
    assert "没有找到可用资料" in events[1]["content"]


def test_switch_off_keeps_original_evidence_without_running_the_builder():
    class Builder:
        def build(self, documents):
            raise AssertionError("disabled builder must not run")

    class Retriever:
        def invoke(self, query):
            return [Document(page_content="原片段")]

    service = RagService(Retriever(), RunnableLambda(lambda _: "回答"), lambda _: InMemoryChatMessageHistory(),
                         context_builder=Builder(), context_entries_enabled=False)
    assert list(service.stream_answer("问题", "off"))[0]["sources"][0]["excerpt"] == "原片段"


def test_provenance_fields_are_validated_and_only_public_keys_are_exposed():
    doc = Document(page_content="正文", metadata={
        "document_hash": "a" * 64,
        "source_spans": [{"start_line": 1, "end_line": 2, "private_path": "private"}],
    })
    public = source_items([doc])[0]
    assert public["source_spans"] == [{"start_line": 1, "end_line": 2}]
    doc.metadata["source_spans"][0]["end_line"] = "private"
    assert "source_spans" not in source_items([doc])[0]
