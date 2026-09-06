"""RAG 项目的 HTTP API，供 Vue 前端调用。"""

import json
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# 在 API 入口自动读取本地 .env；如果用户通过系统环境变量配置，也同样有效。
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from knowledge_base import KnowledgeBaseService
from rag import RagService


app = FastAPI(title="智能客服 RAG API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="user_001", min_length=1, max_length=100)


rag_service: RagService | None = None
knowledge_base_service: KnowledgeBaseService | None = None


def get_rag_service() -> RagService:
    global rag_service
    if rag_service is None:
        rag_service = RagService()
    return rag_service


def get_knowledge_base_service() -> KnowledgeBaseService:
    global knowledge_base_service
    if knowledge_base_service is None:
        knowledge_base_service = KnowledgeBaseService()
    return knowledge_base_service


def sse_event(payload: dict | str) -> str:
    if payload == "[DONE]":
        return "data: [DONE]\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    query = request.input.strip()
    if not query:
        raise HTTPException(status_code=400, detail="问题不能为空")

    def stream() -> Iterator[str]:
        try:
            chain = get_rag_service().chain
            chain_config = {"configurable": {"session_id": request.session_id}}
            for chunk in chain.stream({"input": query}, config=chain_config):
                if chunk:
                    yield sse_event({"content": chunk})
            yield sse_event("[DONE]")
        except Exception as exc:
            yield sse_event({"error": str(exc)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/knowledge/upload")
async def upload_knowledge(request: Request) -> dict[str, str]:
    """接收原始文件流，文件名通过 X-Filename 请求头传递。"""
    filename = unquote(request.headers.get("x-filename", ""))
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if not filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="目前只支持 TXT 文件")

    content = await request.body()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="文件必须使用 UTF-8 编码") from exc

    if not text.strip():
        raise HTTPException(status_code=400, detail="文件内容不能为空")

    try:
        message = get_knowledge_base_service().upload_by_str(text, filename)
        return {"message": message}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"知识库更新失败：{exc}") from exc
