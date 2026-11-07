"""Compatibility command; prefer scripts/ or python -m robot_rag.cli."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from robot_rag.cli.init_database import main

if __name__ == "__main__":
    raise SystemExit(main())
