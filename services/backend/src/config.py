import os
from pathlib import Path
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
load_dotenv(PROJECT_ROOT / ".env")
DATA_ROOT = Path(os.environ.get("RAG_DATA_DIR", str(REPOSITORY_ROOT / "runtime")))
INTERNAL_KNOWLEDGE_DIR = Path(os.environ.get(
    "RAG_KNOWLEDGE_DIR", str(REPOSITORY_ROOT / "knowledge" / "robot")
))

# PostgreSQL + pgvector. Schema initialization is a separate deployment step.
database_url = os.environ.get("DATABASE_URL", "")
embedding_dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))
if not 1 <= embedding_dimensions <= 2000:
    raise ValueError("EMBEDDING_DIMENSIONS must be between 1 and 2000")

# Current chunking baseline; strategy tuning is independent from the layout.
chunk_size = 1000
chunk_overlap = 100

retrieval_top_k = 4
retrieval_mode = os.environ.get("RAG_RETRIEVAL_MODE", "hybrid")
if retrieval_mode not in {"vector", "keyword", "hybrid"}:
    raise ValueError("RAG_RETRIEVAL_MODE must be vector, keyword or hybrid")
retrieval_candidate_k = int(os.environ.get("RAG_RETRIEVAL_CANDIDATES", "10"))
retrieval_rrf_k = int(os.environ.get("RAG_RRF_K", "60"))
if not retrieval_top_k <= retrieval_candidate_k <= 100 or retrieval_rrf_k < 1:
    raise ValueError("Retrieval candidates must be 4..100 and RRF constant must be positive")

_rerank_enabled = os.environ.get("RAG_RERANK_ENABLED", "false").lower()
if _rerank_enabled not in {"true", "false"}:
    raise ValueError("RAG_RERANK_ENABLED must be true or false")
rerank_enabled = _rerank_enabled == "true"
rerank_model = os.environ.get("RAG_RERANK_MODEL", "qwen3-rerank")
rerank_url = os.environ.get("RAG_RERANK_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank")
rerank_timeout = float(os.environ.get("RAG_RERANK_TIMEOUT", "3"))
if not 0 < rerank_timeout <= 30:
    raise ValueError("RAG_RERANK_TIMEOUT must be greater than 0 and at most 30 seconds")

embedding_model_name = os.environ.get("EMBEDDING_MODEL", "text-embedding-v4")
chat_model_name = os.environ.get("CHAT_MODEL", "qwen-plus")

def model_configured() -> bool:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    return bool(key and key != "your_dashscope_api_key_here")
