import json
from types import SimpleNamespace

import pytest

from evaluation.benchmark import bind, checked_dataset, digest


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_binding_changes_uuid_without_changing_question_or_cluster(tmp_path, monkeypatch):
    from src.crud import knowledge
    from src.services import corpus

    original = tmp_path / "original"
    target = tmp_path / "target"
    save(original / "corpus.json", [{"id": "old", "content": "evidence content",
                                      "metadata": {"source": "file.txt", "chunk_index": 0}}])
    save(original / "dataset.json", {"version": "v1", "corpus_sha256": digest(original / "corpus.json"),
        "questions": [{"id": "q1", "source": "file.txt", "evidence": "evidence",
                       "labeled_chunk_ids": ["old"], "cluster": "old", "query": "question", "reference": "answer"}]})
    monkeypatch.setattr(corpus, "load_internal_files", lambda: [SimpleNamespace(document_hash="hash")])
    monkeypatch.setattr(knowledge, "scoped_chunks", lambda *_: [
        ("evidence content", {"source": "file.txt", "chunk_index": 0}, "hash", "new")])
    bind(target, original)
    q = checked_dataset(target)[0]
    assert q["labeled_chunk_ids"] == ["new"]
    assert q["query"] == "question" and q["reference"] == "answer" and q["cluster"] == "old"
    assert json.loads((target / "dataset.json").read_text())["parent_dataset_sha256"] == digest(original / "dataset.json")
    # Reproduction never replaces existing evidence in place.
    with pytest.raises(FileExistsError):
        bind(target, original)


def test_binding_rejects_changed_corpus_before_writing(tmp_path, monkeypatch):
    from src.crud import knowledge
    from src.services import corpus

    original = tmp_path / "original"
    target = tmp_path / "target"
    save(original / "corpus.json", [{"id": "old", "content": "old content",
                                      "metadata": {"source": "file.txt", "chunk_index": 0}}])
    save(original / "dataset.json", {"questions": []})
    monkeypatch.setattr(corpus, "load_internal_files", lambda: [])
    monkeypatch.setattr(knowledge, "scoped_chunks", lambda *_: [])
    with pytest.raises(ValueError, match="differs"):
        bind(target, original)
    assert not target.exists()
