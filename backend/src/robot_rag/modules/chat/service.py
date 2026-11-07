"""Chat use case: preconditions and handoff to the RAG workflow."""
from collections.abc import Callable
from robot_rag.config import model_configured
from robot_rag.modules.rag.service import RagService


class ChatUnavailable(Exception):
    """A safe public message, independent from HTTP transport."""


class EmptyQuestion(Exception):
    pass


class ChatService:
    def __init__(self, rag_factory: Callable[[], RagService], knowledge_status: Callable[[], dict]):
        self.rag_factory = rag_factory
        self.knowledge_status = knowledge_status

    def prepare(self, text: str) -> str:
        if not model_configured():
            raise ChatUnavailable("模型待配置，请管理员配置 DashScope API Key 后启用服务")
        query = text.strip()
        if not query:
            raise EmptyQuestion("问题不能为空")
        if not self.knowledge_status()["ready"]:
            raise ChatUnavailable("内置知识库尚未就绪，请管理员完成资料导入")
        return query

    def stream_answer(self, query: str, session_id: str):
        yield from self.rag_factory().stream_answer(query, session_id)
