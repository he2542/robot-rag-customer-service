from langchain_text_splitters import RecursiveCharacterTextSplitter

from src import config
from src.services.chunking import split_knowledge


def test_entries_keep_questions_answers_and_section_context():
    text = "# 文档\n### 维护\n1. **怎么清洗？**\n- 清水冲洗。\n2. **怎么晾干？**\n- 自然晾干。\n## 故障\n3. 联系售后。"
    assert split_knowledge(text, "问答.txt") == [
        "[来源：问答.txt | 分类：维护]\n1. **怎么清洗？**\n- 清水冲洗。",
        "[来源：问答.txt | 分类：维护]\n2. **怎么晾干？**\n- 自然晾干。",
        "[来源：问答.txt | 分类：故障]\n3. 联系售后。",
    ]


def test_short_unrelated_entries_never_merge():
    assert split_knowledge("1. 电池\n2. 滤网", "资料.txt") == [
        "[来源：资料.txt]\n1. 电池", "[来源：资料.txt]\n2. 滤网"]


def test_long_entry_falls_back_without_merging_next_entry(monkeypatch):
    monkeypatch.setattr(config, "chunk_size", 30)
    monkeypatch.setattr(config, "chunk_overlap", 5)
    chunks = split_knowledge("### 维护\n1. " + "清洁。" * 40 + "\n2. 独立条目", "资料.txt")
    assert len(chunks) > 2
    assert all(chunk.startswith("[来源：资料.txt | 分类：维护]\n") for chunk in chunks)
    assert all(len(chunk.split("\n", 1)[1]) <= 30 for chunk in chunks)
    assert chunks[-1].endswith("\n2. 独立条目")
    assert all("2. 独立条目" not in chunk for chunk in chunks[:-1])


def test_unnumbered_fallback_preserves_original_text(monkeypatch):
    monkeypatch.setattr(config, "chunk_size", 30)
    monkeypatch.setattr(config, "chunk_overlap", 5)
    text = "# 文档\n无编号资料。" * 20
    expected = RecursiveCharacterTextSplitter(
        chunk_size=30, chunk_overlap=5,
        separators=["\n\n", "\n", "。", ".", " ", ""], length_function=len,
    ).split_text(text)
    assert split_knowledge(text, "资料.txt") == ["[来源：资料.txt]\n" + part for part in expected]
