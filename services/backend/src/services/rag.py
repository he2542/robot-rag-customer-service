"""Grounded robot customer-service answers over a managed internal corpus."""

import re

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnableWithMessageHistory

from src import config
from src.history import FileChatMessageHistory
from src.services.retrieval import InternalKnowledgeRetriever

from .prompts import SYSTEM_PROMPT



def internal_history(session_id):
    return FileChatMessageHistory(session_id, str(config.DATA_ROOT / "chat_history" / "robot_internal_v1"))


def format_documents(documents):
    return "\n\n".join(
        f"[S{index}] {document.metadata.get('source', '内置资料')}\n{document.page_content}"
        for index, document in enumerate(documents, 1)
    )


def source_items(documents):
    return [{"id": f"S{index}", "filename": str(document.metadata.get("source", "内置资料")),
             "chunk_index": document.metadata.get("chunk_index", 0),
             "excerpt": document.page_content}
            for index, document in enumerate(documents, 1)]


def filter_citations(text, allowed):
    return re.sub(r"\[\s*((?:S)?\d[^\]\n]*)\]",
                  lambda match: f"[{match.group(1).strip()}]"
                  if match.group(1).strip() in allowed else "", text)


class RagService:
    def __init__(self, retriever=None, chat_model=None, history_factory=internal_history):
        self.retriever = retriever if retriever is not None else InternalKnowledgeRetriever(
            DashScopeEmbeddings(model=config.embedding_model_name)
        )
        self.chat_model = chat_model if chat_model is not None else ChatTongyi(
            model=config.chat_model_name, max_retries=1,
            model_kwargs={"enable_thinking": False, "max_tokens": 1024},
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT), MessagesPlaceholder("history"), ("human", "{input}"),
        ])
        chain = RunnableLambda(lambda value: {
            "input": value["input"], "history": value.get("history", [])[-12:],
            "context": format_documents(value["documents"]),
        }) | prompt | self.chat_model | StrOutputParser()
        self.chain = RunnableWithMessageHistory(
            chain, history_factory, input_messages_key="input", history_messages_key="history",
        )

    def stream_answer(self, query: str, session_id: str):
        risk_terms = ("鼓包", "冒烟", "烧焦", "起火", "漏电", "短接", "带电维修", "拆电池")
        if any(term in query for term in risk_terms):
            yield {"sources": []}
            yield {"content": "涉及电池、电气或起火风险，请停止使用和充电，在确保自身安全的前提下远离设备，联系专业售后；不要自行拆修或继续测试。"}
            return
        documents = self.retriever.invoke(query)
        yield {"sources": source_items(documents)}
        if not documents:
            yield {"content": "当前内置知识库没有找到可用资料，无法据此确认。请补充型号或问题细节，必要时联系对应品牌售后。"}
            return
        allowed = {f"S{index}" for index in range(1, len(documents) + 1)}
        pending = ""
        for chunk in self.chain.stream(
            {"input": query, "documents": documents},
            config={"configurable": {"session_id": session_id}},
        ):
            if not chunk:
                continue
            pending += chunk
            # Keep an incomplete citation until its closing bracket arrives.
            opening = pending.rfind("[")
            boundary = opening if opening >= 0 and "]" not in pending[opening:] else len(pending)
            text, pending = pending[:boundary], pending[boundary:]
            cleaned = filter_citations(text, allowed)
            if cleaned:
                yield {"content": cleaned}
        if pending:
            cleaned = re.sub(r"\[\s*S?\d[^\]\n]*$", "", filter_citations(pending, allowed))
            if cleaned:
                yield {"content": cleaned}


class ChatUnavailable(Exception):
    """Safe public business error; HTTP mapping belongs to routes."""


class EmptyQuestion(Exception):
    pass


def prepare_question(text: str, knowledge: dict) -> str:
    if not config.model_configured():
        raise ChatUnavailable("模型待配置，请管理员配置 DashScope API Key 后启用服务")
    query = text.strip()
    if not query:
        raise EmptyQuestion("问题不能为空")
    if not knowledge["ready"]:
        raise ChatUnavailable("内置知识库尚未就绪，请管理员完成资料导入")
    return query
