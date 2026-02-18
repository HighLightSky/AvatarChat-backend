from dataclasses import dataclass
from typing import Dict, List

from .interview_state_models import InterviewStageType, StageDefinition, StageRuntimeState


@dataclass
class TransitionDecision:
    """阶段切换决策结果。"""

    moved: bool
    from_stage: InterviewStageType
    to_stage: InterviewStageType
    reason: str


class InterviewFlowController:
    """面试阶段顺序流转控制器（MVP）。

    规则：当前阶段达到固定轮数后切换到下一阶段。
    """

    def __init__(self, stage_order: List[str], stage_turn_limits: Dict[str, int]):
        default_order = [
            InterviewStageType.GREETING.value,
            InterviewStageType.TECHNICAL.value,
            InterviewStageType.RESUME.value,
            InterviewStageType.EXPERIENCE.value,
            InterviewStageType.CLOSING.value,
        ]
        if not stage_order:
            stage_order = default_order

        self.stage_definitions: List[StageDefinition] = []
        for stage_name in stage_order:
            stage = InterviewStageType(stage_name)
            # 每阶段至少 1 轮，避免出现无法推进的配置。
            turn_limit = max(stage_turn_limits.get(stage_name, 3), 1)
            self.stage_definitions.append(
                StageDefinition(
                    stage=stage,
                    turn_limit=turn_limit,
                    prompt_hint=f"当前处于{stage.value}阶段，请围绕该阶段推进面试。",
                )
            )

        self.runtime_state = StageRuntimeState()

    def get_current_stage(self) -> StageDefinition:
        """获取当前阶段定义。"""

        idx = min(self.runtime_state.current_stage_index, len(self.stage_definitions) - 1)
        return self.stage_definitions[idx]

    def on_turn_finished(self) -> TransitionDecision:
        """在一轮完成后推进进度，并返回是否发生阶段切换。"""

        current = self.get_current_stage()
        self.runtime_state.current_turn_in_stage += 1
        self.runtime_state.total_turn += 1

        if self.runtime_state.current_turn_in_stage < current.turn_limit:
            return TransitionDecision(
                moved=False,
                from_stage=current.stage,
                to_stage=current.stage,
                reason="turn_limit_not_reached",
            )

        prev_stage = current.stage
        if self.runtime_state.current_stage_index < len(self.stage_definitions) - 1:
            # 未到最后阶段：推进到下一阶段并重置当前阶段轮数。
            self.runtime_state.current_stage_index += 1
            self.runtime_state.current_turn_in_stage = 0
        next_stage = self.get_current_stage().stage
        return TransitionDecision(
            moved=next_stage != prev_stage,
            from_stage=prev_stage,
            to_stage=next_stage,
            reason="turn_limit_reached",
        )

    def should_end_interview(self) -> bool:
        """判断是否满足面试结束条件（最后阶段达到轮数上限）。"""

        current = self.get_current_stage()
        at_last_stage = self.runtime_state.current_stage_index == len(self.stage_definitions) - 1
        if not at_last_stage:
            return False
        return self.runtime_state.current_turn_in_stage >= current.turn_limit

    def export_progress(self) -> Dict:
        """导出可透传给前端或日志的阶段进度信息。"""

        current = self.get_current_stage()
        return {
            "current_stage": current.stage.value,
            "stage_turn": self.runtime_state.current_turn_in_stage,
            "stage_turn_limit": current.turn_limit,
            "total_turn": self.runtime_state.total_turn,
            "stage_index": self.runtime_state.current_stage_index,
            "stage_count": len(self.stage_definitions),
        }
