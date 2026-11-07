from fastapi import APIRouter, Depends, HTTPException
from robot_rag.dependencies import get_knowledge_status
from .schemas import KnowledgeStatus

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("", response_model=KnowledgeStatus)
def knowledge_status(status: dict = Depends(get_knowledge_status)) -> dict:
    return status


@router.post("/upload", include_in_schema=False)
def disabled_upload():
    raise HTTPException(status_code=404, detail="Not Found")
