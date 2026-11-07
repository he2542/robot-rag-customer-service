from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from robot_rag.modules.knowledge.corpus import internal_document_hash, load_internal_files
from robot_rag.modules.rag.service import RagService, source_items, filter_citations


def test_document_identity_changes_with_filename_and_content(tmp_path):
    assert internal_document_hash("内容", "a.txt") != internal_document_hash("内容", "b.txt")
    assert internal_document_hash("内容", "a.txt") != internal_document_hash("新版", "a.txt")
    (tmp_path / "a.txt").write_text("\ufeff内容", encoding="utf-8")
    files = load_internal_files(tmp_path)
    assert files[0].text == "内容"
    assert files[0].document_hash == internal_document_hash("内容", "a.txt")


def test_only_public_metadata_is_returned():
    items = source_items([Document(page_content="原文", metadata={
        "source": "资料.txt", "chunk_index": 2, "private_path": "C:/secret", "token": "secret",
    })])
    assert items == [{"id": "S1", "filename": "资料.txt", "chunk_index": 2, "excerpt": "原文"}]


def test_unknown_citations_and_original_item_numbers_are_not_references():
    assert filter_citations("清理主刷[S1]，说明[7]，错误[S99]。", {"S1"}) == "清理主刷[S1]，说明，错误。"
    assert filter_citations("主刷[S3-7]，正文[S1, S2]。", {"S1", "S2", "S3"}) == "主刷，正文。"


def test_streaming_reference_validation_across_chunk_boundaries():
    class Retriever:
        def invoke(self, query):
            return [Document(page_content="资料", metadata={"source": "资料.txt"})]
    class SplitChain:
        def stream(self, value, config):
            yield from ("回答[S", "1]，错误[S3", "-7]，未知[99]，未闭合[S8")
    service = RagService(Retriever(), RunnableLambda(lambda _: "unused"))
    service.chain = SplitChain()
    answer = "".join(event.get("content", "") for event in service.stream_answer("问题", "split"))
    assert answer == "回答[S1]，错误，未知，未闭合"


def test_empty_retrieval_refuses_without_model_call():
    class Empty:
        def invoke(self, query):
            return []
    calls = []
    service = RagService(Empty(), RunnableLambda(lambda value: calls.append(value) or "错误回答"))
    events = list(service.stream_answer("问题", "empty-test"))
    assert events[0] == {"sources": []}
    assert "没有找到" in events[1]["content"] and not calls


def test_high_risk_question_does_not_retrieve_or_generate():
    class MustNotCall:
        def invoke(self, query):
            raise AssertionError("should not retrieve")
    service = RagService(MustNotCall(), RunnableLambda(lambda _: "不得生成"))
    events = list(service.stream_answer("电池鼓包能不能拆电池？", "risk-test"))
    assert events[0] == {"sources": []}
    assert "不要自行拆修" in events[1]["content"]


def test_same_documents_ground_generation_and_sources_with_history():
    class Retriever:
        def invoke(self, query):
            return [Document(page_content="请清理主刷。", metadata={"source": "维护保养.txt", "chunk_index": 0})]
    histories, prompts = {}, []
    def history(session_id):
        return histories.setdefault(session_id, InMemoryChatMessageHistory())
    def model(prompt):
        prompts.append(prompt.to_messages())
        return "清理主刷。[S1]"
    service = RagService(Retriever(), RunnableLambda(model), history)
    events = list(service.stream_answer("主刷卡住了", "conversation"))
    assert events[0]["sources"][0]["excerpt"] == "请清理主刷。"
    assert "[S1] 维护保养.txt\n请清理主刷。" in prompts[0][0].content
    assert "清理主刷。[S1]" == "".join(event.get("content", "") for event in events)
    list(service.stream_answer("那滤网呢？", "conversation"))
    assert len(histories["conversation"].messages) == 4
    assert any(message.content == "主刷卡住了" for message in prompts[1])
