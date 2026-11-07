from pydantic import BaseModel


class KnowledgeFileStatus(BaseModel):
    filename: str
    chunks: int


class KnowledgeStatus(BaseModel):
    ready: bool
    files: list[KnowledgeFileStatus]
    chunk_count: int
    scope_note: str
