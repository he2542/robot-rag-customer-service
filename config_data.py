from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

md5_path = str(PROJECT_ROOT / "md5.text")

#Chroma向量数据库的配置
collection_name = "rag"
persist_directory = str(PROJECT_ROOT / "chroma_db")

#spliter
chunk_size = 1000
chunk_overlap = 100
separators = ["\n\n", "\n", " ", "",".","?","!",",",""]
max_spliter_char_number=1000

#
similarity_threshold = 2   #检索返回匹配的文档数量阈值

embedding_model_name = "text-embedding-v4"
chat_model_name = "qwen3-max"

session_config = {
        "configurable":{
            "session_id":"user_001"
        }
    }
