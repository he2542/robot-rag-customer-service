"""HTTP/SSE transport only; business preconditions live in ChatService."""
import logging
from typing import Iterator
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from robot_rag.dependencies import get_chat_service
from robot_rag.shared.sse import sse_event
from .schemas import ChatRequest
from .service import ChatService, ChatUnavailable, EmptyQuestion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
def chat(request: ChatRequest, service: ChatService = Depends(get_chat_service)) -> StreamingResponse:
    try:
        query = service.prepare(request.input)
    except ChatUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmptyQuestion as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    def stream() -> Iterator[str]:
        try:
            for payload in service.stream_answer(query, request.session_id):
                yield sse_event(payload)
            yield sse_event("[DONE]")
        except Exception as exc:
            logger.error("Chat request failed (%s)", type(exc).__name__)
            yield sse_event({"error": "问答服务暂时不可用，请稍后重试"})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
