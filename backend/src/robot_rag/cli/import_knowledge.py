"""Preview or explicitly import administrator-maintained TXT files."""

import argparse
import json

from robot_rag.modules.knowledge.corpus import load_internal_files
from robot_rag.modules.knowledge.service import KnowledgeBaseService
from langchain_text_splitters import RecursiveCharacterTextSplitter
from robot_rag import config


def main() -> int:
    parser = argparse.ArgumentParser(description="内置知识库导入；默认仅预览，不调用模型")
    parser.add_argument("--apply", action="store_true", help="调用嵌入模型并写入已初始化的数据库")
    args = parser.parse_args()
    try:
        files = load_internal_files()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " ", ""], length_function=len,
        )
        preview = [{"filename": file.filename, "characters": len(file.text),
                    "chunks": len(splitter.split_text(file.text))} for file in files]
        print(json.dumps({"mode": "apply" if args.apply else "preview", "files": preview,
                          "total_chunks": sum(item["chunks"] for item in preview)}, ensure_ascii=False))
        if not args.apply:
            return 0
        service = KnowledgeBaseService()
        for file in files:
            result = service.upload_by_str(file.text, file.filename, internal=True)
            print(json.dumps({"filename": file.filename, "result": result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Do not print database URLs, credentials or provider error bodies.
        print(f"导入未完成（{type(exc).__name__}）。请核对资料、模型和数据库配置；已完成文件可断点续跑。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
