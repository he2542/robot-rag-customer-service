from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from robot_rag.config import model_configured
from robot_rag.dependencies import get_knowledge_status
from robot_rag.shared.database import database_ready
from .schemas import HealthStatus

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthStatus)
def health(knowledge: dict = Depends(get_knowledge_status)) -> JSONResponse:
    ready = database_ready()
    status = HealthStatus(status="ok" if ready else "degraded", model_configured=model_configured(),
                          database_ready=ready, knowledge_ready=knowledge["ready"])
    return JSONResponse(status_code=200 if ready else 503, content=status.model_dump())
