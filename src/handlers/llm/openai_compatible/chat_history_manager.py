"""OpenAI 兼容 LLM 的历史消息管理。

该模块负责两件事：
1) 维护会话轮次历史（用户/数字人）；
2) 将内部历史结构转换为 OpenAI Chat Completions 的 messages 格式。
"""

from dataclasses import dataclass
import re
from typing import Literal, Optional

from engine_utils.media_utils import ImageUtils

@dataclass
class HistoryMessage:
    """单条历史消息。

    role: 内部角色标识，仅区分 human/avatar。
    content: 文本内容。
    timestamp: 预留字段，当前逻辑未参与消息拼装。
    """
    role: Optional[Literal['avatar', 'human']] = None
    content: str = ''
    timestamp: Optional[str] = None

name_dict = {
    # 内部角色到 OpenAI 角色的映射。
    "avatar": "assistant",
    "human": "user"
}

def filter_text(text):
    """过滤文本中不在白名单内的字符，降低模型输入噪声。"""
    pattern = r"[^a-zA-Z0-9\u4e00-\u9fff,.\~!?，。！？ ]"  # 匹配不在范围内的字符
    filtered_text = re.sub(pattern, "", text)
    return filtered_text

class ChatHistory:
    """会话历史容器。

    注意：当前实现使用 `while len(history) >= max_history_length` 裁剪，
    因此有效保留条数会小于 max_history_length（严格来说是上限-1）。
    """

    def __init__(self, history_length):
        # 历史窗口大小（由 handler 配置 history_length 注入）。
        self.max_history_length = history_length
        # 历史列表，按时间顺序追加。
        self.message_history = []

    def add_message(self, message: HistoryMessage):
        """追加单条消息，并进行窗口裁剪。"""
        history = self.message_history
        history.append(message)
        # thread safe
        while len(history) >= self.max_history_length:
            history.pop(0)

    def generate_next_messages(self, chat_text, images):
        """生成下一轮请求的 messages。

        规则：
        1) 先放已有历史（avatar/human -> assistant/user）；
        2) 再追加当前轮用户输入；
        3) 如果携带图片，按多模态 content(list) 结构拼装。
        """

        def history_to_message(history: HistoryMessage):
            # 历史消息统一做文本过滤，避免脏字符影响模型行为。
            return {
                "role": name_dict[history.role],
                "content": filter_text(history.content),
            }
        history = self.message_history
        messages = list(map(history_to_message, history))
        if images and len(images) > 0:
            # 多模态输入：当前轮 user 消息由 text + image_url 组成。
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": filter_text(chat_text),
                    },
                # 图片通过工具函数转为模型可识别 URL（如 data URL）。
                ] + (list(map(lambda x: {"type": "image_url", "image_url": {"url": ImageUtils.format_image(x)}}, images)))
            })
        else: 
            # 纯文本输入场景。
            messages.append({
                "role": "user",
                "content": filter_text(chat_text),
            })

        return messages