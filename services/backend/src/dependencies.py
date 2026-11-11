"""Service construction; routes obtain replaceable dependencies here."""
from functools import lru_cache
from src.services.rag import RagService
from src.services.retrieval import internal_knowledge_status


@lru_cache(maxsize=1)
def get_rag_service() -> RagService:
    return RagService()


def get_rag_factory():
    return get_rag_service


def get_knowledge_status() -> dict:
    return internal_knowledge_status()
