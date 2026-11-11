from typing import Literal
from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded"]
    model_configured: bool
    storage_backend: str = "postgresql+pgvector"
    database_ready: bool
    knowledge_ready: bool
