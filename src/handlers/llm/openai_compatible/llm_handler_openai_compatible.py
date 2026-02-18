

"""OpenAI 兼容模型的 LLM Handler。

职责概述：
1) 接收 HUMAN_TEXT / 可选 CAMERA_VIDEO 输入；
2) 按 `human_text_end` 进行轮次切分并触发一次 LLM 推理；
3) 以流式方式输出 AVATAR_TEXT；
4) 维护每个 session 独立的历史上下文。
"""

import os
import re
from typing import Dict, Optional, cast
from loguru import logger
from pydantic import BaseModel, Field
from abc import ABC
from openai import APIStatusError, OpenAI
from chat_engine.contexts.handler_context import HandlerContext
from chat_engine.data_models.chat_engine_config_data import ChatEngineConfigModel, HandlerBaseConfigModel
from chat_engine.common.handler_base import HandlerBase, HandlerBaseInfo, HandlerDataInfo, HandlerDetail
from chat_engine.data_models.chat_data.chat_data_model import ChatData
from chat_engine.data_models.chat_data_type import ChatDataType
from chat_engine.contexts.session_context import SessionContext
from chat_engine.data_models.runtime_data.data_bundle import DataBundle, DataBundleDefinition, DataBundleEntry
from handlers.llm.openai_compatible.chat_history_manager import ChatHistory, HistoryMessage


class LLMConfig(HandlerBaseConfigModel, BaseModel):
    """LLM Handler 配置项。"""

    model_name: str = Field(default="qwen-plus")
    system_prompt: str = Field(default="请你扮演一个 AI 助手，用简短的对话来回答用户的问题，并在对话内容中加入合适的标点符号，不需要加入标点符号相关的内容")
    api_key: str = Field(default=os.getenv("DASHSCOPE_API_KEY"))
    api_url: str = Field(default=None)
    enable_video_input: bool = Field(default=False)
    history_length: int = Field(default=20)


class LLMContext(HandlerContext):
    def __init__(self, session_id: str):
        super().__init__(session_id)
        # 配置与客户端
        self.config = None
        self.local_session_id = 0
        self.model_name = None
        self.system_prompt = None
        self.api_key = None
        self.api_url = None
        self.client = None
        # 当前轮输入/输出暂存（按 text_end 收敛为一轮）
        self.input_texts = ""
        self.output_texts = ""
        # 当前最新视频帧（可选多模态输入）
        self.current_image = None
        # 会话级历史，随 session 生命周期存在
        self.history = None
        self.enable_video_input = False


class HandlerLLM(HandlerBase, ABC):
    def __init__(self):
        super().__init__()

    def get_handler_info(self) -> HandlerBaseInfo:
        # 向引擎声明配置模型，供配置解析与注入。
        return HandlerBaseInfo(
            config_model=LLMConfig,
        )

    def get_handler_detail(self, session_context: SessionContext,
                           context: HandlerContext) -> HandlerDetail:
        # 声明输出载荷结构：avatar_text（文本）。
        definition = DataBundleDefinition()
        definition.add_entry(DataBundleEntry.create_text_entry("avatar_text"))
        # 输入声明：文本必需，视频可选（仅在 enable_video_input=True 时消费）。
        inputs = {
            ChatDataType.HUMAN_TEXT: HandlerDataInfo(
                type=ChatDataType.HUMAN_TEXT,
            ),
            ChatDataType.CAMERA_VIDEO: HandlerDataInfo(
                type=ChatDataType.CAMERA_VIDEO,
            ),
        }
        outputs = {
            ChatDataType.AVATAR_TEXT: HandlerDataInfo(
                type=ChatDataType.AVATAR_TEXT,
                definition=definition,
            )
        }
        return HandlerDetail(
            inputs=inputs, outputs=outputs,
        )

    def load(self, engine_config: ChatEngineConfigModel, handler_config: Optional[BaseModel] = None):
        # 启动期做关键参数校验，避免运行时才报错。
        if isinstance(handler_config, LLMConfig):
            if handler_config.api_key is None or len(handler_config.api_key) == 0:
                error_message = 'api_key is required in config/xxx.yaml, when use handler_llm'
                logger.error(error_message)
                raise ValueError(error_message)

    def create_context(self, session_context, handler_config=None):
        # 为每个 session 创建独立上下文：历史、输入缓存、OpenAI client 互不干扰。
        if not isinstance(handler_config, LLMConfig):
            handler_config = LLMConfig()
        context = LLMContext(session_context.session_info.session_id)
        context.model_name = handler_config.model_name
        context.system_prompt = {'role': 'system', 'content': handler_config.system_prompt}
        context.api_key = handler_config.api_key
        context.api_url = handler_config.api_url
        context.enable_video_input = handler_config.enable_video_input
        context.history = ChatHistory(history_length=handler_config.history_length)
        context.client = OpenAI(
            # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx",
            api_key=context.api_key,
            base_url=context.api_url,
        )
        return context
    
    def start_context(self, session_context, handler_context):
        pass

    def handle(self, context: HandlerContext, inputs: ChatData,
               output_definitions: Dict[ChatDataType, HandlerDataInfo]):
        """处理单条输入并在“本轮结束”时触发一次 LLM。

        轮次触发条件：收到 HUMAN_TEXT 且 `human_text_end=True`。
        在此之前，文本会持续累加到 `context.input_texts`。
        """
        output_definition = output_definitions.get(ChatDataType.AVATAR_TEXT).definition
        context = cast(LLMContext, context)
        text = None
        if inputs.type == ChatDataType.CAMERA_VIDEO and context.enable_video_input:
            # 视频输入只更新“最新帧”，并不单独触发推理。
            context.current_image = inputs.data.get_main_data()
            return
        elif inputs.type == ChatDataType.HUMAN_TEXT:
            text = inputs.data.get_main_data()
        else:
            return
        speech_id = inputs.data.get_meta("speech_id")
        if (speech_id is None):
            # 兜底：没有外部 speech_id 时，回退到 session_id。
            speech_id = context.session_id

        if text is not None:
            # 增量文本（例如 ASR 分段）先拼接，等待结束标记。
            context.input_texts += text

        text_end = inputs.data.get_meta("human_text_end", False)
        if not text_end:
            # 未到轮次末尾，不调用模型。
            return

        chat_text = context.input_texts
        # 清理协议标记，防止污染提示词。
        chat_text = re.sub(r"<\|.*?\|>", "", chat_text)
        if len(chat_text) < 1:
            return
        logger.info(f'llm input {context.model_name} {chat_text} ')
        current_content = context.history.generate_next_messages(chat_text, 
                                                                 [context.current_image] if context.current_image is not None else [])
        logger.debug(f'llm input {context.model_name} {current_content} ')
        try:
            completion = context.client.chat.completions.create(
                model=context.model_name,  # 此处以qwen-plus为例，可按需更换模型名称。模型列表：https://help.aliyun.com/zh/model-studio/getting-started/models
                messages=[
                    context.system_prompt,
                ] + current_content,
                stream=True,
                stream_options={"include_usage": True}
            )
            # 一旦开始本轮请求，先清空输入缓存并重置输出累积。
            context.current_image = None
            context.input_texts = ''
            context.output_texts = ''
            for chunk in completion:
                if (chunk and chunk.choices and chunk.choices[0] and chunk.choices[0].delta.content):
                    output_text = chunk.choices[0].delta.content
                    context.output_texts += output_text
                    logger.info(output_text)
                    output = DataBundle(output_definition)
                    output.set_main_data(output_text)
                    # 流式分片，持续发送中间文本。
                    output.add_meta("avatar_text_end", False)
                    # 透传 speech_id，供下游 TTS/渲染链路对齐同一轮。
                    output.add_meta("speech_id", speech_id)
                    yield output
            # 仅在本轮完整结束后写入历史，避免半截回复污染上下文。
            context.history.add_message(HistoryMessage(role="human", content=chat_text))
            context.history.add_message(HistoryMessage(role="avatar", content=context.output_texts))
        except Exception as e:
            logger.error(e)
            if (isinstance(e, APIStatusError)):
                response = e.body
                if isinstance(response, dict) and "message" in response:
                    response = f"{response['message']}"
            output_text = response 
            output = DataBundle(output_definition)
            output.set_main_data(output_text)
            # 错误信息也走同样输出通道，保障链路一致性。
            output.add_meta("avatar_text_end", False)
            output.add_meta("speech_id", speech_id)
            yield output
        context.input_texts = ''
        context.output_texts = ''
        logger.info('avatar text end')
        end_output = DataBundle(output_definition)
        end_output.set_main_data('')
        # 轮次终止标志：通知下游该轮文本已结束。
        end_output.add_meta("avatar_text_end", True)
        end_output.add_meta("speech_id", speech_id)
        yield end_output

    def destroy_context(self, context: HandlerContext):
        pass

