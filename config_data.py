import os
from pathlib import Path
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
DATA_ROOT = Path(os.environ.get("RAG_DATA_DIR", str(PROJECT_ROOT)))

# PostgreSQL + pgvector. Schema initialization is a separate deployment step.
database_url = os.environ.get("DATABASE_URL", "")
embedding_dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))
if not 1 <= embedding_dimensions <= 2000:
    raise ValueError("EMBEDDING_DIMENSIONS must be between 1 and 2000")

#spliter
chunk_size = 1000
chunk_overlap = 100
separators = ["\n\n", "\n", " ", "",".","?","!",",",""]
max_spliter_char_number=1000

#
similarity_threshold = 2   #检索返回匹配的文档数量阈值

embedding_model_name = os.environ.get("EMBEDDING_MODEL", "text-embedding-v4")
chat_model_name = os.environ.get("CHAT_MODEL", "qwen3-max")

session_config = {
        "configurable":{
            "session_id":"user_001"
        }
    }
