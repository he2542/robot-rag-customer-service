import os
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from src import config
from src.database import connection as database
from src.history import FileChatMessageHistory
from src.services.corpus import load_internal_files


def test_corpus_cache_reuses_reads_and_invalidates_changes(tmp_path, monkeypatch):
    source = tmp_path / "a.txt"
    source.write_text("old", encoding="utf-8")
    reads = []
    read_text = Path.read_text

    def read(path, *args, **kwargs):
        reads.append(path)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    first = load_internal_files(tmp_path)
    first.clear()  # Callers cannot mutate the cached snapshot.
    assert load_internal_files(tmp_path)[0].text == "old"
    assert len(reads) == 1
    source.write_text("new", encoding="utf-8")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    changed = load_internal_files(tmp_path)[0]
    assert changed.text == "new" and len(reads) == 2
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.txt").write_text("other", encoding="utf-8")
    assert load_internal_files(other)[0].text == "other"
    (tmp_path / "b.txt").write_text("added", encoding="utf-8")
    assert len(load_internal_files(tmp_path)) == 2
    source.unlink()
    assert [file.filename for file in load_internal_files(tmp_path)] == ["b.txt"]


def test_history_bounds_and_failed_replace_preserves_file(tmp_path, monkeypatch):
    history = FileChatMessageHistory("session", str(tmp_path))
    history.add_messages([HumanMessage(content=str(i)) for i in range(50)])
    assert [message.content for message in history.messages] == [str(i) for i in range(10, 50)]
    saved = Path(history.file_path).read_bytes()

    def fail_replace(source, target):
        assert Path(source).parent == Path(target).parent
        raise OSError("simulated failed replacement")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError):
            history.add_messages([HumanMessage(content="new")])
    assert Path(history.file_path).read_bytes() == saved
    assert list(tmp_path.iterdir()) == [Path(history.file_path)]
    history.clear()
    assert history.messages == []


def test_pool_is_lazy_reused_and_can_be_reopened(monkeypatch):
    pools = []

    class Pool:
        check_connection = object()

        def __init__(self, conninfo, **kwargs):
            self.conninfo, self.kwargs, self.closed = conninfo, kwargs, False
            pools.append(self)

        def connection(self):
            return self

        def close(self):
            self.closed = True

    database.close_pool()
    monkeypatch.setattr(database, "ConnectionPool", Pool)
    monkeypatch.setattr(config, "database_url", "postgresql+psycopg://localhost/robot_rag_test")
    try:
        assert not pools
        assert database.connect() is database.connect()
        assert len(pools) == 1
        assert pools[0].conninfo == "postgresql://localhost/robot_rag_test"
        database.close_pool()
        assert pools[0].closed
        database.connect()
        assert len(pools) == 2
    finally:
        database.close_pool()


def test_embedding_check_still_accepts_monkeypatched_connect(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql):
            return self

        def fetchone(self):
            return config.embedding_model_name, config.embedding_dimensions

    monkeypatch.setattr(database, "connect", Connection)
    database.check_embedding_configuration()
    monkeypatch.setattr(config, "embedding_model_name", "changed")
    connection = Connection()
    connection.fetchone = lambda: ("original", config.embedding_dimensions)
    with pytest.raises(ValueError, match="不匹配"):
        database.check_embedding_configuration(connection)
