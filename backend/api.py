"""Compatibility entry; implementation lives in src/robot_rag/main.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from robot_rag.main import app  # noqa: E402,F401
