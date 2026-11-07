"""Application assembly. Run: uvicorn robot_rag.main:app --app-dir src."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from robot_rag.config import PROJECT_ROOT
from robot_rag.modules.chat.router import router as chat_router
from robot_rag.modules.knowledge.router import router as knowledge_router
from robot_rag.modules.health.router import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="智能客服 RAG API", version="1.0.0")
    app.add_middleware(CORSMiddleware,
                       allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(health_router)
    app.include_router(knowledge_router)
    app.include_router(chat_router)
    frontend_dist = PROJECT_ROOT.parent / "frontend" / "dist"
    if os.environ.get("RAG_SERVE_FRONTEND") == "1" and frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


app = create_app()
