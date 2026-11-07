"""Version identities for administrator-managed internal TXT documents."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from robot_rag import config

KNOWLEDGE_BASE = "robot-internal-v1"
SCOPE_NOTE = "资料来自扫地机器人课程示例，非品牌官方手册；型号参数、保修和维修操作请以对应产品官方说明为准。"


@dataclass(frozen=True)
class KnowledgeFile:
    filename: str
    text: str
    document_hash: str


def internal_document_hash(text: str, filename: str) -> str:
    identity = f"{KNOWLEDGE_BASE}\0{filename}\0{text}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def load_internal_files(directory: Path | None = None) -> list[KnowledgeFile]:
    folder = directory if directory is not None else config.INTERNAL_KNOWLEDGE_DIR
    files = []
    for path in sorted(folder.glob("*.txt")):
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            raise ValueError("知识资料必须为不超过 1 MB 的普通 TXT 文件")
        text = path.read_text(encoding="utf-8-sig")
        if not text.strip() or len(path.name) > 128:
            raise ValueError("知识资料为空或文件名过长")
        files.append(KnowledgeFile(path.name, text, internal_document_hash(text, path.name)))
    if not files:
        raise ValueError("内置知识资料目录为空，请管理员准备 TXT 资料")
    return files
