"""Composition root for request dependencies and the lazy RAG instance."""
from functools import lru_cache
from robot_rag.modules.chat.service import ChatService
from robot_rag.modules.rag.service import RagService
from robot_rag.modules.knowledge.service import internal_knowledge_status


@lru_cache(maxsize=1)
def get_rag_service() -> RagService:
    return RagService()


def get_knowledge_status() -> dict:
    return internal_knowledge_status()


def get_chat_service() -> ChatService:
    return ChatService(get_rag_service, get_knowledge_status)
