"""模拟面试场景的 OpenAI 兼容 LLM Handler（MVP）。

核心行为：
1) 接收 HUMAN_TEXT（可选 CAMERA_VIDEO）；
2) 以 human_text_end 为轮次触发条件；
3) 进行流式输出并打 avatar_text_end 标记；
4) 按固定轮数推进面试阶段；
5) 本地构建 checkpoint（不对接业务后端）。
"""

import os
import re
from abc import ABC
from typing import Dict, Optional, cast
from uuid import uuid4

from loguru import logger
from openai import APIStatusError, OpenAI
from pydantic import BaseModel, Field

from chat_engine.common.handler_base import HandlerBase, HandlerBaseInfo, HandlerDataInfo, HandlerDetail
from chat_engine.contexts.handler_context import HandlerContext
from chat_engine.contexts.session_context import SessionContext
from chat_engine.data_models.chat_data.chat_data_model import ChatData
from chat_engine.data_models.chat_data_type import ChatDataType
from chat_engine.data_models.chat_engine_config_data import ChatEngineConfigModel, HandlerBaseConfigModel
from chat_engine.data_models.runtime_data.data_bundle import DataBundle, DataBundleDefinition, DataBundleEntry

from .interview_flow_controller import InterviewFlowController
from .interview_history_manager import InterviewHistoryManager
from .interview_state_models import CheckpointPayload
from .ports import EvaluationPort, NullEvaluationPort, NullRagPort, RagPort


class InterviewLLMConfig(HandlerBaseConfigModel, BaseModel):
    """模拟面试 LLM Handler 的配置项。"""

    model_name: str = Field(default="qwen-plus")
    system_prompt: str = Field(default="你是模拟面试官，请按阶段推进面试并给出简洁、专业的问题与反馈。")
    api_key: str = Field(default=os.getenv("DASHSCOPE_API_KEY"))
    api_url: str = Field(default=None)
    enable_video_input: bool = Field(default=False)
    history_length: int = Field(default=20)

    stage_order: list[str] = Field(default_factory=lambda: ["greeting", "technical", "resume", "experience", "closing"])
    stage_turn_limits: Dict[str, int] = Field(default_factory=lambda: {
        "greeting": 2,
        "technical": 3,
        "resume": 3,
        "experience": 2,
        "closing": 1,
    })

    checkpoint_enabled: bool = Field(default=True)


class InterviewLLMContext(HandlerContext):
    """单个 session 的运行时上下文。"""

    def __init__(self, session_id: str):
        super().__init__(session_id)
        # 模型与客户端
        self.model_name = None
        self.system_prompt = None
        self.api_key = None
        self.api_url = None
        self.client = None

        # 当前轮输入输出缓存
        self.input_texts = ""
        self.output_texts = ""
        self.current_image = None
        self.enable_video_input = False

        # 会话级能力组件
        self.history: Optional[InterviewHistoryManager] = None
        self.flow_controller: Optional[InterviewFlowController] = None

        # 扩展能力端口（MVP 默认 Null Object）
        self.rag_port: RagPort = NullRagPort()
        self.evaluation_port: EvaluationPort = NullEvaluationPort()

        # 本地 checkpoint 缓存
        self.local_checkpoints: list[CheckpointPayload] = []
        self.checkpoint_enabled = True
        self.interview_finished = False


class HandlerInterviewLLM(HandlerBase, ABC):
    def get_handler_info(self) -> HandlerBaseInfo:
        # 声明配置模型，供引擎自动解析注入。
        return HandlerBaseInfo(config_model=InterviewLLMConfig)

    def get_handler_detail(self, session_context: SessionContext, context: HandlerContext) -> HandlerDetail:
        # 声明输出结构：avatar_text。
        definition = DataBundleDefinition()
        definition.add_entry(DataBundleEntry.create_text_entry("avatar_text"))

        inputs = {
            ChatDataType.HUMAN_TEXT: HandlerDataInfo(type=ChatDataType.HUMAN_TEXT),
            ChatDataType.CAMERA_VIDEO: HandlerDataInfo(type=ChatDataType.CAMERA_VIDEO),
        }
        outputs = {
            ChatDataType.AVATAR_TEXT: HandlerDataInfo(type=ChatDataType.AVATAR_TEXT, definition=definition),
        }
        return HandlerDetail(inputs=inputs, outputs=outputs)

    def load(self, engine_config: ChatEngineConfigModel, handler_config: Optional[BaseModel] = None):
        # 启动期参数校验。
        if isinstance(handler_config, InterviewLLMConfig):
            if not handler_config.api_key:
                raise ValueError("api_key is required in config when use interview llm handler")

    def create_context(self, session_context: SessionContext, handler_config=None):
        # 为每个 session 创建独立上下文，避免跨会话污染。
        if not isinstance(handler_config, InterviewLLMConfig):
            handler_config = InterviewLLMConfig()

        context = InterviewLLMContext(session_context.session_info.session_id)
        context.model_name = handler_config.model_name
        context.system_prompt = {"role": "system", "content": handler_config.system_prompt}
        context.api_key = handler_config.api_key
        context.api_url = handler_config.api_url
        context.enable_video_input = handler_config.enable_video_input
        context.history = InterviewHistoryManager(history_length=handler_config.history_length)
        context.flow_controller = InterviewFlowController(
            stage_order=handler_config.stage_order,
            stage_turn_limits=handler_config.stage_turn_limits,
        )
        context.checkpoint_enabled = handler_config.checkpoint_enabled
        context.client = OpenAI(api_key=context.api_key, base_url=context.api_url)
        return context

    def start_context(self, session_context, handler_context):
        pass

    def handle(self, context: HandlerContext, inputs: ChatData, output_definitions: Dict[ChatDataType, HandlerDataInfo]):
        """处理单条输入并在轮次结束时触发一次 LLM 推理。"""

        output_definition = output_definitions.get(ChatDataType.AVATAR_TEXT).definition
        context = cast(InterviewLLMContext, context)

        if context.interview_finished:
            # 已结束会话不再继续生成。
            return

        if inputs.type == ChatDataType.CAMERA_VIDEO and context.enable_video_input:
            # 视频帧仅更新上下文，不直接触发推理。
            context.current_image = inputs.data.get_main_data()
            return
        if inputs.type != ChatDataType.HUMAN_TEXT:
            return

        text = inputs.data.get_main_data() or ""
        speech_id = inputs.data.get_meta("speech_id") or context.session_id
        # 累积增量文本，等待 human_text_end 收敛为完整一轮。
        context.input_texts += text

        if not inputs.data.get_meta("human_text_end", False):
            return

        # 清理协议标记，避免污染提示词。
        chat_text = re.sub(r"<\|.*?\|>", "", context.input_texts)
        if len(chat_text.strip()) < 1:
            context.input_texts = ""
            return

        # 获取当前阶段并执行（可选）RAG。
        stage = context.flow_controller.get_current_stage()
        rag_result = context.rag_port.retrieve(chat_text, stage.stage.value, context.session_id)

        current_messages = context.history.to_openai_messages(stage_hint=stage.prompt_hint, current_user_text=chat_text)
        if rag_result.content:
            current_messages.append({
                "role": "system",
                "content": f"可参考知识：{rag_result.content}",
            })

        try:
            completion = context.client.chat.completions.create(
                model=context.model_name,
                messages=[context.system_prompt] + current_messages,
                stream=True,
                stream_options={"include_usage": True},
            )
            # 开始本轮生成时重置临时缓存。
            context.output_texts = ""
            context.input_texts = ""
            context.current_image = None

            for chunk in completion:
                if chunk and chunk.choices and chunk.choices[0] and chunk.choices[0].delta.content:
                    output_text = chunk.choices[0].delta.content
                    context.output_texts += output_text
                    output = DataBundle(output_definition)
                    output.set_main_data(output_text)
                    # 流式中间片段。
                    output.add_meta("avatar_text_end", False)
                    output.add_meta("speech_id", speech_id)
                    yield output

            # 本轮成功后写入历史，再做评估和阶段推进。
            turn_index = context.flow_controller.runtime_state.total_turn + 1
            stage_name = stage.stage.value
            context.history.add_human_message(chat_text, stage=stage_name, turn_index=turn_index)
            context.history.add_avatar_message(context.output_texts, stage=stage_name, turn_index=turn_index)

            eval_result = context.evaluation_port.evaluate_turn(chat_text, context.output_texts, stage_name)
            transition = context.flow_controller.on_turn_finished()

            if context.checkpoint_enabled:
                # MVP：只做本地 checkpoint 构建，不上报外部系统。
                checkpoint = self._build_checkpoint_payload(context, speech_id, chat_text, context.output_texts, eval_result.scores, rag_result.metadata)
                context.local_checkpoints.append(checkpoint)
                logger.debug(f"local checkpoint built: {checkpoint.checkpoint_id}")

            if transition.moved:
                logger.info(f"Interview stage moved: {transition.from_stage.value} -> {transition.to_stage.value}")

            if context.flow_controller.should_end_interview():
                context.interview_finished = True

        except Exception as e:
            # 异常也复用 AVATAR_TEXT 输出通道，保证链路一致。
            logger.error(e)
            output_text = str(e)
            if isinstance(e, APIStatusError):
                body = e.body
                if isinstance(body, dict) and "message" in body:
                    output_text = str(body["message"])
            output = DataBundle(output_definition)
            output.set_main_data(output_text)
            output.add_meta("avatar_text_end", False)
            output.add_meta("speech_id", speech_id)
            yield output

        context.input_texts = ""
        context.output_texts = ""
        end_output = DataBundle(output_definition)
        end_output.set_main_data("")
        # 轮次结束标记。
        end_output.add_meta("avatar_text_end", True)
        end_output.add_meta("speech_id", speech_id)
        end_output.add_meta("interview_finished", context.interview_finished)
        if context.flow_controller is not None:
            end_output.add_meta("interview_progress", context.flow_controller.export_progress())
        yield end_output

    def _build_checkpoint_payload(
        self,
        context: InterviewLLMContext,
        speech_id: str,
        human_text: str,
        avatar_text: str,
        eval_scores: Dict,
        rag_context: Dict,
    ) -> CheckpointPayload:
        """构建本地 checkpoint 载荷。"""

        progress = context.flow_controller.export_progress() if context.flow_controller else {}
        return CheckpointPayload(
            checkpoint_id=f"cp-{uuid4()}",
            session_id=context.session_id,
            stage=progress.get("current_stage", "unknown"),
            stage_turn=progress.get("stage_turn", 0),
            total_turn=progress.get("total_turn", 0),
            human_text=human_text,
            avatar_text=avatar_text,
            eval_scores=eval_scores or {},
            rag_context=rag_context or {},
            extra={
                "speech_id": speech_id,
                "history_snapshot": context.history.build_checkpoint_snapshot() if context.history else {},
            },
        )

    def destroy_context(self, context: HandlerContext):
        pass
