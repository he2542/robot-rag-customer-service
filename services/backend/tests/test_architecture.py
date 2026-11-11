"""Guard the selected dependency direction without testing file counts or size."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"


def imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            yield from (name.name for name in node.names)


def test_business_and_persistence_do_not_depend_on_http_or_ui():
    for layer in ("services", "crud", "database"):
        for path in (ROOT / layer).glob("*.py"):
            for name in imports(path):
                assert not name.startswith(("fastapi", "starlette", "src.routes", "src.schemas")), (path, name)


def test_routes_do_not_use_sql_or_provider_clients():
    for path in (ROOT / "routes").glob("*.py"):
        for name in imports(path):
            assert not name.startswith(("src.crud", "psycopg", "pgvector", "dashscope", "langchain")), (path, name)


def test_crud_and_database_do_not_depend_on_services():
    for layer in ("crud", "database"):
        for path in (ROOT / layer).glob("*.py"):
            assert all(not name.startswith("src.services") for name in imports(path)), path
