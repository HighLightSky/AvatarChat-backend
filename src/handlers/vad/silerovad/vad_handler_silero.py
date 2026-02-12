"""
Silero VAD Handler - 基于 Silero 模型的语音活动检测处理器

该 Handler 用于检测音频流中的人声活动，识别说话的开始和结束时刻。
主要功能：
1. 实时检测音频中的人声片段
2. 过滤静音和噪音
3. 标记人声的开始和结束边界
4. 输出完整的人声片段供后续处理
"""

import enum
import math
import os
from abc import ABC
from typing import cast, Dict, Optional, Tuple

import numpy as np
from loguru import logger
from pydantic import BaseModel, Field

from chat_engine.common.handler_base import HandlerBase, HandlerDetail, HandlerDataInfo, HandlerBaseInfo
from chat_engine.data_models.chat_data_type import ChatDataType
from chat_engine.contexts.handler_context import HandlerContext
from chat_engine.contexts.session_context import SessionContext
from chat_engine.data_models.chat_data.chat_data_model import ChatData
from chat_engine.data_models.chat_engine_config_data import ChatEngineConfigModel, HandlerBaseConfigModel
from chat_engine.data_models.runtime_data.data_bundle import DataBundle, DataBundleDefinition, DataBundleEntry
from engine_utils.general_slicer import SliceContext, slice_data


class SileroVADConfigModel(HandlerBaseConfigModel, BaseModel):
    """
    Silero VAD 配置模型
    
    配置参数说明：
    - speaking_threshold: 语音检测阈值（0-1），超过此值认为是人声
    - start_delay: 开始延迟（采样点数），连续检测到人声超过此长度才确认为说话开始
    - end_delay: 结束延迟（采样点数），连续静音超过此长度才确认为说话结束
    - buffer_look_back: 回溯缓冲区大小（采样点数），说话开始时向前回溯的音频长度
    - speech_padding: 语音填充（采样点数），在人声片段前后添加的静音填充
    """
    speaking_threshold: float = Field(default=0.5)
    start_delay: int = Field(default=2048)
    end_delay: int = Field(default=5000)
    buffer_look_back: int = Field(default=1024)
    speech_padding: int = Field(default=512)


class SpeakingStatus(enum.Enum):
    """
    说话状态枚举
    
    PRE_START: 预开始状态，检测到人声但还未达到确认阈值
    START: 说话中状态，已确认人声开始
    END: 结束状态，当前没有检测到人声
    """
    PRE_START = enum.auto()
    START = enum.auto()
    END = enum.auto()


class HumanAudioVADContext(HandlerContext):
    """
    人声音频 VAD 上下文
    
    维护 VAD 检测的状态信息，包括：
    - 当前说话状态
    - 音频历史缓冲区
    - 人声和静音的持续时长
    - 模型状态
    """
    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.config: SileroVADConfigModel = SileroVADConfigModel()
        self.speaking_status = SpeakingStatus.END  # 当前说话状态

        self.clip_size = 512  # 每个音频片段的大小（采样点数）

        self.audio_history = []  # 音频历史缓冲区，存储 (音频片段, 时间戳) 元组
        self.history_length_limit = 0  # 历史缓冲区长度限制

        self.speech_length: int = 0  # 当前连续人声的长度（采样点数）
        self.silence_length: int = 0  # 当前连续静音的长度（采样点数）

        self.shared_states = None  # 共享状态对象

        self.model_state: Optional[np.ndarray] = None  # Silero 模型的内部状态
        self.slice_context: Optional[SliceContext] = None  # 音频切片上下文

        self.speech_id: int = 0  # 人声片段 ID 计数器

    def reset(self):
        """重置上下文状态，清空历史和计数器"""
        self.audio_history.clear()
        self.speech_length = 0
        self.silence_length = 0
        self.slice_context.flush()

    def _update_status_on_pre_start(self, clip: np.ndarray, _timestamp: Optional[int] = None):
        """
        处理预开始状态的更新
        
        当连续人声长度达到 start_delay 阈值时，确认说话开始，
        从历史缓冲区中提取音频片段（包括回溯部分），并添加前置填充。
        
        返回：
            - 音频数据和额外参数（如果确认开始）
            - None 和空字典（如果还未确认或回退到结束状态）
        """
        if self.speech_length >= self.config.start_delay:
            head_sample_id = None
            self.speaking_status = SpeakingStatus.START
            # 计算需要提取的音频长度（回溯 + 开始延迟）
            sample_num_to_fetch = self.config.buffer_look_back + self.config.start_delay
            slice_num_to_fetch = math.ceil(sample_num_to_fetch / self.clip_size)
            audio_clips = []
            # 从历史缓冲区中提取音频片段
            for history_entry in self.audio_history[-slice_num_to_fetch:]:
                history_clip, history_timestamp = history_entry
                if head_sample_id is None:
                    head_sample_id = history_timestamp
                audio_clips.append(history_clip)
            output_audio = np.concatenate(audio_clips, axis=0)
            # 在音频前添加静音填充
            output_audio = np.concatenate(
                [np.zeros(self.config.speech_padding, dtype=clip.dtype), output_audio], axis=0)
            self.speech_id += 1
            logger.info("Start of human speech")
            extra_args =  {
                "human_speech_start": True,
                "pre_padding": self.config.speech_padding,
            }
            if head_sample_id is not None:
                extra_args["head_sample_id"] = head_sample_id
                logger.info(f"VAD pre_start to start got timestamp {head_sample_id}")
            return output_audio, extra_args
        else:
            # 如果出现静音，回退到结束状态
            if self.silence_length > 0:
                logger.info("Back to not started status")
                self.speaking_status = SpeakingStatus.END
            return None, {}

    def _update_status_on_start(self, clip: np.ndarray, timestamp: Optional[int] = None):
        """
        处理说话中状态的更新
        
        当连续静音长度达到 end_delay 阈值时，确认说话结束，
        在音频片段后添加后置填充。
        
        返回：
            - 音频数据和额外参数（包含时间戳）
        """
        if self.silence_length >= self.config.end_delay:
            # 确认说话结束
            self.speaking_status = SpeakingStatus.END
            # 在音频后添加静音填充
            output_audio = np.concatenate(
                [clip, np.zeros(self.config.speech_padding, dtype=clip.dtype)], axis=0)
            logger.info("End of human speech")
            extra_args =  {
                "human_speech_end": True,
                "post_padding": self.config.speech_padding,
            }
            if timestamp is not None:
                extra_args["head_sample_id"] = timestamp
                logger.info(f"VAD start to start got timestamp {timestamp}")
            return output_audio,  extra_args
        else:
            # 继续说话中，直接返回当前音频片段
            return clip, {"head_sample_id": timestamp}

    def _update_status_on_end(self, _clip: np.ndarray, _timestamp: Optional[int] = None):
        """
        处理结束状态的更新
        
        如果检测到人声，转换到预开始状态。
        
        返回：
            - None 和空字典（结束状态不输出音频）
        """
        if self.speech_length > 0:
            logger.info("Pre start of new human speech")
            self.speaking_status = SpeakingStatus.PRE_START
        return None, {}

    def _append_to_history(self, clip: np.ndarray, timestamp: Optional[int] = None):
        """
        将音频片段添加到历史缓冲区
        
        如果缓冲区超过长度限制，移除最旧的片段。
        """
        self.audio_history.append((clip, timestamp))
        while 0 < self.history_length_limit < len(self.audio_history):
            self.audio_history.pop(0)

    def update_status(self, speech_prob: float, clip: np.ndarray,
                      timestamp: Optional[int]=None) -> Tuple[Optional[np.ndarray], Dict]:
        """
        根据语音概率更新状态
        
        参数：
            speech_prob: 当前音频片段的语音概率（0-1）
            clip: 当前音频片段
            timestamp: 时间戳（可选）
        
        返回：
            - 输出音频数据（如果有）
            - 额外参数字典（包含状态标记和元数据）
        
        逻辑：
        1. 将音频片段添加到历史缓冲区
        2. 根据语音概率更新人声/静音长度计数器
        3. 根据当前状态调用相应的状态更新方法
        """
        self._append_to_history(clip, timestamp)
        # 根据语音概率更新计数器
        if speech_prob > self.config.speaking_threshold:
            self.speech_length += self.clip_size
            self.silence_length = 0
        else:
            self.silence_length += self.clip_size
            self.speech_length = 0
        # 根据当前状态调用相应的处理方法
        if self.speaking_status == SpeakingStatus.PRE_START:
            return self._update_status_on_pre_start(clip, timestamp)
        elif self.speaking_status == SpeakingStatus.START:
            return self._update_status_on_start(clip, timestamp)
        elif self.speaking_status == SpeakingStatus.END:
            return self._update_status_on_end(clip, timestamp)


class HandlerAudioVAD(HandlerBase, ABC):
    """
    音频 VAD Handler 主类
    
    负责：
    1. 加载 Silero VAD ONNX 模型
    2. 创建和管理 VAD 上下文
    3. 处理输入的麦克风音频流
    4. 输出检测到的人声片段
    """
    def __init__(self):
        super().__init__()
        self.model = None  # ONNX 模型实例

    def get_handler_info(self):
        """
        返回 Handler 基本信息
        
        指定使用的配置模型类型
        """
        return HandlerBaseInfo(
            config_model=SileroVADConfigModel
        )

    def load(self, engine_config: ChatEngineConfigModel, handler_config = None):
        """
        加载 Silero VAD ONNX 模型
        
        使用 ONNX Runtime 加载预训练的 VAD 模型，
        配置为单线程 CPU 执行以优化性能。
        """
        import onnxruntime
        model_name = "silero_vad.onnx"
        model_path = os.path.join(self.handler_root, "silero_vad",
                                  "src", "silero_vad", "data",
                                  model_name)
        # 配置 ONNX Runtime 选项
        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1  # 操作间并行线程数
        options.intra_op_num_threads = 1  # 操作内并行线程数
        options.log_severity_level = 4  # 日志级别（4=ERROR）
        self.model = onnxruntime.InferenceSession(model_path,
                                                  providers=["CPUExecutionProvider"],
                                                  sess_options=options)

    def create_context(self, session_context: SessionContext, handler_config = None) -> HandlerContext:
        """
        为每个会话创建 VAD 上下文
        
        初始化：
        1. 上下文配置
        2. 模型状态（用于 RNN 的隐藏状态）
        3. 音频切片上下文
        4. 历史缓冲区长度限制
        """
        context = HumanAudioVADContext(session_context.session_info.session_id)
        context.shared_states = session_context.shared_states
        if isinstance(handler_config, SileroVADConfigModel):
            context.config = handler_config
        # 初始化模型状态（Silero VAD 使用 RNN，需要维护隐藏状态）
        context.model_state = np.zeros((2, 1, 128), dtype=np.float32)
        # 创建音频切片上下文，用于将连续音频流切分为固定大小的片段
        context.slice_context = SliceContext.create_numpy_slice_context(
            slice_size=context.clip_size,
            slice_axis=0,
        )
        # 计算历史缓冲区需要保留的片段数量
        context.history_length_limit = math.ceil((context.config.start_delay + context.config.buffer_look_back)
                                                 / context.clip_size)
        return context

    def start_context(self, session_context, handler_context):
        """
        启动上下文（当前为空实现）
        """
        pass

    def get_handler_detail(self, session_context: SessionContext,
                           context: HandlerContext) -> HandlerDetail:
        """
        定义 Handler 的输入输出规格
        
        输入：MIC_AUDIO（麦克风音频）
        输出：HUMAN_AUDIO（人声音频，单声道 16kHz）
        """
        # 定义输出数据格式
        definition = DataBundleDefinition()
        definition.add_entry(DataBundleEntry.create_audio_entry("human_audio", 1, 16000))

        inputs = {
            ChatDataType.MIC_AUDIO: HandlerDataInfo(
                type=ChatDataType.MIC_AUDIO
            )
        }
        outputs = {ChatDataType.HUMAN_AUDIO: HandlerDataInfo(
                type=ChatDataType.HUMAN_AUDIO,
                definition=definition
            )
        }
        return HandlerDetail(
            inputs=inputs,
            outputs=outputs,
        )

    def _inference(self, context: HumanAudioVADContext, clip: np.ndarray, sr: int=16000):
        """
        使用 Silero VAD 模型进行推理
        
        参数：
            context: VAD 上下文（包含模型状态）
            clip: 音频片段（numpy 数组）
            sr: 采样率（默认 16000Hz）
        
        返回：
            语音概率（0-1 之间的浮点数）
        
        注意：
        - 模型需要 1 维音频输入
        - 模型状态会在推理过程中更新（RNN 的隐藏状态）
        """
        clip = clip.squeeze()
        if clip.ndim != 1:
            logger.warning("Input audio should be 1-dim array")
            return 0
        clip = np.expand_dims(clip, axis=0)
        # 准备模型输入
        inputs = {
            "input": clip,
            "sr": np.array([sr], dtype=np.int64),
            "state": context.model_state
        }
        # 执行推理
        prob, state = self.model.run(None, inputs)
        # 更新模型状态
        context.model_state = state
        return prob[0][0]

    def handle(self, context: HandlerContext, inputs: ChatData,
               output_definitions: Dict[ChatDataType, HandlerDataInfo]):
        """
        处理输入的音频数据
        
        主要流程：
        1. 检查 VAD 是否启用
        2. 验证输入数据类型
        3. 提取和预处理音频数据
        4. 将音频切分为固定大小的片段
        5. 对每个片段进行 VAD 推理
        6. 根据推理结果更新状态
        7. 输出检测到的人声片段
        
        参数：
            context: Handler 上下文
            inputs: 输入的聊天数据（麦克风音频）
            output_definitions: 输出数据定义
        
        生成：
            检测到的人声音频片段（ChatData 对象）
        """
        context = cast(HumanAudioVADContext, context)
        output_definition = output_definitions.get(ChatDataType.HUMAN_AUDIO).definition
        # 检查 VAD 是否启用
        if not context.shared_states.enable_vad:
            return
        # 验证输入数据类型
        if inputs.type != ChatDataType.MIC_AUDIO:
            return

        # 提取音频数据
        audio = inputs.data.get_main_data()
        if audio is None:
            return
        audio_entry = inputs.data.get_main_definition_entry()
        sample_rate = audio_entry.sample_rate
        audio = audio.squeeze()

        # 提取时间戳
        timestamp = None
        if inputs.is_timestamp_valid():
            timestamp = inputs.timestamp

        # 音频数据类型转换（归一化到 [-1, 1]）
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / 32767

        # 更新切片上下文的起始索引
        context.slice_context.update_start_id(timestamp[0], force_update=False)

        # 逐片段处理音频
        for clip in slice_data(context.slice_context, audio):
            head_sample_id = context.slice_context.get_last_slice_start_index()
            # 对当前片段进行 VAD 推理
            speech_prob = self._inference(context, clip)
            # 根据语音概率更新状态
            audio_clip, extra_args = context.update_status(speech_prob, clip, timestamp=head_sample_id)
            # FIXME: 这是一个临时方案，在人声结束后禁用 VAD
            # 理想情况下应该由客户端或下游 Handler 处理
            human_speech_end = extra_args.get("human_speech_end", False)
            timestamp = extra_args.get("head_sample_id", head_sample_id)
            speech_id = f"speech-{context.session_id}-{context.speech_id}"
            if human_speech_end:
                context.shared_states.enable_vad = False
                context.reset()
            # 如果有输出音频，封装为 ChatData 并返回
            if audio_clip is not None:
                output = DataBundle(output_definition)
                output.set_main_data(np.expand_dims(audio_clip, axis=0))
                # 添加元数据（开始/结束标记、填充信息等）
                for flag_name, flag_value in extra_args.items():
                    output.add_meta(flag_name, flag_value)
                output.add_meta("speech_id", speech_id)
                output_chat_data = ChatData(
                    type=ChatDataType.HUMAN_AUDIO,
                    data=output
                )
                # 设置时间戳
                if timestamp >= 0:
                    output_chat_data.timestamp = timestamp, sample_rate
                yield output_chat_data

    def destroy_context(self, context: HandlerContext):
        """
        销毁上下文（当前为空实现）
        
        在会话结束时调用，用于清理资源
        """
        pass
