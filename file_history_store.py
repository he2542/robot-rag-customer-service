import os
import json
from pathlib import Path
from langchain_core.chat_history import BaseChatMessageHistory
from typing import Sequence, List
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict


def get_history(session_id):
    storage_path = Path(__file__).resolve().parent / "chat_history"
    return FileChatMessageHistory(session_id, str(storage_path))

class FileChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id: str, storage_path: str):
        self.session_id = session_id
        self.storage_path = storage_path
        self.file_path = os.path.join(self.storage_path, self.session_id)
        # 确保存储目录存在
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        # 获取已有消息并合并新消息
        all_messages = list(self.messages)
        all_messages.extend(messages)
        # 将消息转为字典并写入文件
        new_messages = [message_to_dict(message) for message in all_messages]
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(new_messages, f)

    @property
    def messages(self) -> List[BaseMessage]:
        try:
            # 从文件读取消息数据
            with open(self.file_path, "r", encoding="utf-8") as f:
                messages_data = json.load(f)
            # 将字典转回BaseMessage对象
            return messages_from_dict(messages_data)
        except FileNotFoundError:
            # 文件不存在时返回空列表
            return []

    def clear(self) -> None:
        # 清空文件内容
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump([], f)

