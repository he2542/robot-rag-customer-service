import pytest
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from src.services.rag import RagService


@pytest.mark.parametrize("result", [" 扫地机器人滤网怎么清洗？ ", "", "   ", RuntimeError("unavailable")])
def test_rewrite_only_followups_and_preserve_original_history(result):
    history = InMemoryChatMessageHistory()
    queries, calls = [], []

    class Retriever:
        def invoke(self, query):
            queries.append(query)
            return [Document(page_content="维护资料")]

    def rewrite(value):
        calls.append(value)
        if isinstance(result, Exception):
            raise result
        return result

    service = RagService(Retriever(), RunnableLambda(lambda _: "回答[S1]"), lambda _: history,
                         query_rewriter=RunnableLambda(rewrite))
    list(service.stream_answer("机器人怎么保养？", "test"))
    assert not calls
    list(service.stream_answer("那滤网呢？", "test"))
    assert len(calls) == 1
    assert calls[0]["query"] == "那滤网呢？"
    assert calls[0]["history"][0].content == "机器人怎么保养？"
    expected = result.strip() if isinstance(result, str) and result.strip() else "那滤网呢？"
    assert queries == ["机器人怎么保养？", expected]
    assert [message.content for message in history.messages if message.type == "human"] == [
        "机器人怎么保养？", "那滤网呢？"]


def test_rewriter_receives_only_recent_messages():
    history = InMemoryChatMessageHistory(messages=[HumanMessage(content=str(i)) for i in range(20)])
    calls = []

    class EmptyRetriever:
        def invoke(self, query):
            return []

    service = RagService(EmptyRetriever(), RunnableLambda(lambda _: "unused"), lambda _: history,
                         query_rewriter=RunnableLambda(lambda value: calls.append(value) or "独立问题"))
    list(service.stream_answer("那它呢？", "test"))
    assert [message.content for message in calls[0]["history"]] == [str(i) for i in range(8, 20)]
