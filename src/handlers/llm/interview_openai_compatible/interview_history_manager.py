import re
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


@dataclass
class HistoryMessage:
    """单条历史消息（带阶段与轮次信息）。"""

    role: Literal["human", "avatar"]
    content: str
    stage: str
    turn_index: int


_ROLE_MAPPING = {
    "human": "user",
    "avatar": "assistant",
}


def filter_text(text: str) -> str:
    """过滤异常字符，减少提示词噪声。"""

    pattern = r"[^a-zA-Z0-9\u4e00-\u9fff,.\~!?，。！？ ]"
    return re.sub(pattern, "", text)


class InterviewHistoryManager:
    """面试会话历史管理器。"""

    def __init__(self, history_length: int):
        # 至少保留 2 条，避免窗口过小导致上下文失真。
        self.max_history_length = max(history_length, 2)
        self.message_history: List[HistoryMessage] = []

    def add_human_message(self, text: str, stage: str, turn_index: int):
        self._add_message(HistoryMessage(role="human", content=text, stage=stage, turn_index=turn_index))

    def add_avatar_message(self, text: str, stage: str, turn_index: int):
        self._add_message(HistoryMessage(role="avatar", content=text, stage=stage, turn_index=turn_index))

    def _add_message(self, message: HistoryMessage):
        self.message_history.append(message)
        # 窗口裁剪：仅保留最近 max_history_length 条。
        while len(self.message_history) > self.max_history_length:
            self.message_history.pop(0)

    def to_openai_messages(self, stage_hint: str = "", current_user_text: str = "") -> List[Dict]:
        """转换为 OpenAI Chat Completions 所需 messages 结构。"""

        messages: List[Dict] = []
        for item in self.message_history:
            messages.append({
                "role": _ROLE_MAPPING[item.role],
                "content": filter_text(item.content),
            })
        if current_user_text:
            user_text = filter_text(current_user_text)
            if stage_hint:
                # 将阶段提示拼入当前用户输入，作为轻量阶段约束。
                user_text = f"[{stage_hint}] {user_text}"
            messages.append({
                "role": "user",
                "content": user_text,
            })
        return messages

    def build_checkpoint_snapshot(self) -> Dict:
        """导出 checkpoint 所需的轻量历史快照。"""

        return {
            "history_size": len(self.message_history),
            "recent_messages": [
                {
                    "role": item.role,
                    "content": item.content,
                    "stage": item.stage,
                    "turn_index": item.turn_index,
                }
                for item in self.message_history[-10:]
            ],
        }
