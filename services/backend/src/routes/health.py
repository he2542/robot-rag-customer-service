from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from src.config import model_configured
from src.dependencies import get_knowledge_status
from src.database.connection import database_ready
from src.schemas.health import HealthStatus

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthStatus)
def health(knowledge: dict = Depends(get_knowledge_status)) -> JSONResponse:
    ready = database_ready()
    status = HealthStatus(status="ok" if ready else "degraded", model_configured=model_configured(),
                          database_ready=ready, knowledge_ready=knowledge["ready"])
    return JSONResponse(status_code=200 if ready else 503, content=status.model_dump())
