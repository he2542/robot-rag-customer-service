"""Chinese BM25 over a single, version-scoped snapshot of database chunks."""
import re
import unicodedata

import jieba
from langchain_core.documents import Document
from rank_bm25 import BM25Okapi


_PARTS = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*|[\u3400-\u9fff]+")
_STOPWORDS = frozenset({"的", "了", "呢", "吗", "呀", "啊", "我", "你", "我们", "请", "一下",
                        "怎么", "如何", "为什么", "什么", "是否", "有没有", "一个"})


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    tokens = []
    for part in _PARTS.findall(text):
        words = jieba.lcut_for_search(part, HMM=False) if part[0] >= "\u3400" else [part]
        tokens.extend(word for word in words if word.strip() and word not in _STOPWORDS)
    return tokens


class KeywordIndex:
    """Immutable after construction; one instance may serve concurrent queries."""

    def __init__(self, documents: list[Document]):
        self.documents = tuple(documents)
        tokenized = [tokenize(document.page_content) for document in documents]
        self.terms = tuple(frozenset(tokens) for tokens in tokenized)
        self.model = BM25Okapi(tokenized) if any(tokenized) else None

    def search(self, query: str, limit: int) -> list[Document]:
        tokens = tokenize(query)
        if not tokens or self.model is None:
            return []
        terms = frozenset(tokens)
        scores = self.model.get_scores(tokens)
        # Actual overlap is required. Common terms can have zero/negative BM25
        # scores in a tiny corpus; their sign alone is not a match predicate.
        matched = [index for index, words in enumerate(self.terms) if words & terms]
        matched.sort(key=lambda index: (-float(scores[index]), self.documents[index].id))
        return [self.documents[index] for index in matched[:limit]]
