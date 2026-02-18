from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class InterviewStageType(str, Enum):
    """面试阶段枚举（MVP 固定顺序）。"""

    GREETING = "greeting"
    TECHNICAL = "technical"
    RESUME = "resume"
    EXPERIENCE = "experience"
    CLOSING = "closing"


@dataclass
class StageDefinition:
    """阶段定义：包含阶段类型、轮次上限与提示词片段。"""

    stage: InterviewStageType
    turn_limit: int = 3
    prompt_hint: str = ""


@dataclass
class StageRuntimeState:
    """阶段运行时状态：记录当前阶段索引与轮次进度。"""

    current_stage_index: int = 0
    current_turn_in_stage: int = 0
    total_turn: int = 0


@dataclass
class TurnResult:
    """单轮结果（预留给后续策略/评估扩展）。"""

    speech_id: str
    human_text: str
    avatar_text: str
    stage: InterviewStageType
    turn_index: int
    turn_index_in_stage: int


@dataclass
class CheckpointPayload:
    """本地 checkpoint 数据结构（当前仅内存保存，不对外发送）。"""

    checkpoint_id: str
    session_id: str
    stage: str
    stage_turn: int
    total_turn: int
    human_text: str
    avatar_text: str
    eval_scores: Dict[str, Any] = field(default_factory=dict)
    rag_context: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RagResult:
    """RAG 扩展结果（MVP 默认空）。"""

    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """实时评估扩展结果（MVP 默认空）。"""

    scores: Dict[str, float] = field(default_factory=dict)
    summary: str = ""
    metadata: Optional[Dict[str, Any]] = None
