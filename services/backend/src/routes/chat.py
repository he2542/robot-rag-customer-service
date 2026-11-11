"""HTTP/SSE transport; business preconditions live in services/rag.py."""
import logging
import json
from collections.abc import Callable
from typing import Iterator
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from src.dependencies import get_rag_factory, get_knowledge_status
from src.schemas.chat import ChatRequest
from src.services.rag import RagService, prepare_question, ChatUnavailable, EmptyQuestion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, factory: Callable[[], RagService] = Depends(get_rag_factory),
         status: dict = Depends(get_knowledge_status)) -> StreamingResponse:
    try:
        query = prepare_question(request.input, status)
    except ChatUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmptyQuestion as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def stream() -> Iterator[str]:
        try:
            for payload in factory().stream_answer(query, request.session_id):
                yield sse_event(payload)
            yield sse_event("[DONE]")
        except Exception as exc:
            logger.error("Chat request failed (%s)", type(exc).__name__)
            yield sse_event({"error": "问答服务暂时不可用，请稍后重试"})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


def sse_event(payload: dict | str) -> str:
    if payload == "[DONE]":
        return "data: [DONE]\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
