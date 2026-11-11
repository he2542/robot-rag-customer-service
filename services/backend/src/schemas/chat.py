"""Public chat request contract, independent from database entities."""
from uuid import uuid4
from pydantic import BaseModel, Field
class ChatRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
