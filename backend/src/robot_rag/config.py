import os
from pathlib import Path
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
DATA_ROOT = Path(os.environ.get("RAG_DATA_DIR", str(PROJECT_ROOT)))
INTERNAL_KNOWLEDGE_DIR = Path(os.environ.get(
    "RAG_KNOWLEDGE_DIR", str(PROJECT_ROOT.parent / "knowledge" / "robot")
))

# PostgreSQL + pgvector. Schema initialization is a separate deployment step.
database_url = os.environ.get("DATABASE_URL", "")
embedding_dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))
if not 1 <= embedding_dimensions <= 2000:
    raise ValueError("EMBEDDING_DIMENSIONS must be between 1 and 2000")

# Current chunking baseline; strategy tuning is independent from the layout.
chunk_size = 1000
chunk_overlap = 100

# Compatibility adapter uses 2; the active internal retriever uses 4.
similarity_threshold = 2
retrieval_top_k = 4

embedding_model_name = os.environ.get("EMBEDDING_MODEL", "text-embedding-v4")
chat_model_name = os.environ.get("CHAT_MODEL", "qwen-plus")

def model_configured() -> bool:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    return bool(key and key != "your_dashscope_api_key_here")
