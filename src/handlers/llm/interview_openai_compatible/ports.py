from abc import ABC, abstractmethod

from .interview_state_models import EvalResult, RagResult


class RagPort(ABC):
    """RAG 能力抽象端口。"""

    @abstractmethod
    def retrieve(self, query: str, stage: str, session_id: str) -> RagResult:
        """返回当前轮可用的检索上下文。"""


class EvaluationPort(ABC):
    """实时评估能力抽象端口。"""

    @abstractmethod
    def evaluate_turn(self, human_text: str, avatar_text: str, stage: str) -> EvalResult:
        """返回当前轮实时评估结果。"""


class NullRagPort(RagPort):
    """MVP 空实现。

    建议实现：
    接入向量检索客户端，返回 top-k 片段与来源元数据
    （如 doc_id / chunk_id / score）。
    """

    def retrieve(self, query: str, stage: str, session_id: str) -> RagResult:
        return RagResult(content="", metadata={"enabled": False, "reason": "null_port"})


class NullEvaluationPort(EvaluationPort):
    """MVP 空实现。

    建议实现：
    接入评估服务，按阶段输出维度评分
    （如表达清晰度、准确性、深度、沟通能力）。
    """

    def evaluate_turn(self, human_text: str, avatar_text: str, stage: str) -> EvalResult:
        return EvalResult(scores={}, summary="", metadata={"enabled": False, "reason": "null_port"})
