"""Preview or explicitly import administrator-maintained TXT files."""

import argparse
from src.database.schema import init_database
import json

from src.services.corpus import load_internal_files
from src.services.ingestion import KnowledgeBaseService
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src import config


def import_knowledge(apply: bool = False) -> int:
    try:
        files = load_internal_files()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap,
            separators=["\n\n", "\n", "。", ".", " ", ""], length_function=len,
        )
        preview = [{"filename": file.filename, "characters": len(file.text),
                    "chunks": len(splitter.split_text(file.text))} for file in files]
        print(json.dumps({"mode": "apply" if apply else "preview", "files": preview,
                          "total_chunks": sum(item["chunks"] for item in preview)}, ensure_ascii=False))
        if not apply:
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



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="机器人知识库管理")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import-knowledge", help="预览或导入内部 TXT")
    importer.add_argument("--apply", action="store_true", help="调用嵌入模型并写入已初始化的数据库")
    commands.add_parser("init-db", help="显式初始化业务表，需先启用 pgvector")
    args = parser.parse_args(argv)
    if args.command == "import-knowledge":
        return import_knowledge(args.apply)
    try:
        init_database()
    except Exception as exc:
        print(f"初始化未完成（{type(exc).__name__}），请核对数据库配置与扩展。")
        return 1
    print("PostgreSQL vector schema ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
