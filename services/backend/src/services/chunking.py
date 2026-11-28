"""Keep numbered knowledge entries together with their source context."""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src import config


def split_knowledge(text: str, filename: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap,
        separators=["\n\n", "\n", "。", ".", " ", ""], length_function=len,
    )
    entries, lines = [], []
    section = ""
    entry_section = ""
    numbered = False

    def flush():
        if lines:
            entries.append((entry_section, "\n".join(lines).strip()))
            lines.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            heading, separator, title = stripped.partition(" ")
            if separator and heading.strip("#") == "":
                section = title.strip() if len(heading) > 1 else ""
            continue
        number, separator, _ = stripped.partition(". ")
        if separator and number.isdecimal():
            flush()
            numbered = True
            entry_section = section
        if numbered:
            lines.append(line)
    flush()
    if not numbered:
        entries = [("", text)]

    chunks = []
    for heading, entry in entries:
        prefix = f"[来源：{filename}" + (f" | 分类：{heading}" if heading else "") + "]\n"
        parts = splitter.split_text(entry) if len(entry) > config.chunk_size else [entry]
        chunks.extend(prefix + part for part in parts if part.strip())
    return chunks
