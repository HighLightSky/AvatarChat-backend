"""
ChatEngine - 聊天引擎核心类

这是整个系统的核心管理类，负责：
1. 管理所有 Handler 的生命周期（加载、初始化、销毁）
2. 管理所有会话（Session）的创建和销毁
3. 协调 Handler 和 Session 之间的交互
4. 提供统一的引擎初始化和关闭接口

架构说明：
- ChatEngine: 引擎单例，管理全局资源
- HandlerManager: Handler 管理器，负责 Handler 的注册和查找
- ChatSession: 会话实例，每个用户连接对应一个会话
- Handler: 处理器，实现具体的功能（ASR、TTS、VAD 等）
"""

import os
import uuid
from typing import Optional, Dict

from loguru import logger

from chat_engine.common.client_handler_base import ClientHandlerBase
from chat_engine.contexts.session_context import SessionContext
from chat_engine.core.chat_session import ChatSession
from chat_engine.core.handler_manager import HandlerManager
from chat_engine.data_models.chat_engine_config_data import ChatEngineConfigModel, EngineChannelType
from chat_engine.data_models.session_info_data import SessionInfoData, IOQueueType
from engine_utils.directory_info import DirectoryInfo
from dotenv import load_dotenv


class ChatEngine(object):
    """
    聊天引擎主类
    
    职责：
    1. 引擎生命周期管理（初始化、关闭）
    2. Handler 管理（通过 HandlerManager）
    3. 会话管理（创建、停止、查找）
    4. 配置管理
    """
    def __init__(self):
        self.inited = False  # 初始化标志
        self.engine_config: Optional[ChatEngineConfigModel] = None  # 引擎配置
        self.handler_manager: HandlerManager = HandlerManager(self)  # Handler 管理器

        self.sessions: Dict[str, ChatSession] = {}  # 会话字典，key 为 session_id

    def initialize(self, engine_config: ChatEngineConfigModel, app=None):
        """
        初始化聊天引擎
        
        执行步骤：
        1. 检查是否已初始化（防止重复初始化）
        2. 加载环境变量（从 .env 文件）
        3. 保存引擎配置
        4. 处理模型根目录路径（转换为绝对路径）
        5. 初始化 Handler 管理器
        6. 加载所有配置的 Handlers
        
        参数：
            engine_config: 引擎配置对象
            app: FastAPI 应用实例（用于注册 API 路由）
            ui: Gradio UI 实例（用于添加 UI 组件）
            parent_block: Gradio 父容器（用于嵌套 UI 组件）
        """
        if self.inited:
            return

        # 加载 .env 文件中的环境变量
        load_dotenv()

        self.engine_config = engine_config
        # 将相对路径转换为绝对路径
        if not os.path.isabs(engine_config.model_root):
            engine_config.model_root = os.path.join(DirectoryInfo.get_project_dir(), engine_config.model_root)
        
        # 初始化 Handler 管理器并加载所有 Handlers
        self.handler_manager.initialize(engine_config)
        self.handler_manager.load_handlers(engine_config, app)
        self.inited = True

    def _create_session(self, session_info: SessionInfoData,
                        input_queues: Dict[EngineChannelType, IOQueueType],
                        output_queues: Dict[EngineChannelType, IOQueueType]):
        """
        创建会话（内部方法）
        
        执行步骤：
        1. 生成或验证 session_id
        2. 检查会话是否已存在（防止重复创建）
        3. 创建会话上下文（包含会话信息和 I/O 队列）
        4. 创建会话实例
        5. 为会话准备所有启用的 Handlers（除了 ClientHandler）
        6. 将会话添加到会话字典
        
        注意：ClientHandler 的初始化由其内部逻辑处理，不在此处调用
        
        参数：
            session_info: 会话信息（包含 session_id 等）
            input_queues: 输入队列字典
            output_queues: 输出队列字典
        
        返回：
            创建的会话实例
        """
        # 如果没有提供 session_id，自动生成一个 UUID
        if not session_info.session_id:
            session_info.session_id = str(uuid.uuid4())
        if session_info.session_id in self.sessions:
            raise RuntimeError(f"session {session_info.session_id} already exists")

        # 创建会话上下文
        session_context = SessionContext(session_info=session_info,
                                         input_queues=input_queues,
                                         output_queues=output_queues)

        # 创建会话实例
        session = ChatSession(session_context, self.engine_config)
        
        # 为会话准备所有启用的 Handlers
        handlers = self.handler_manager.get_enabled_handler_registries()
        for registry in handlers:
            if isinstance(registry.handler, ClientHandlerBase):
                # ClientHandler 的 create_context 和 data_sink 创建由其内部逻辑处理
                # 在其他所有 handlers 准备好之后才会被调用
                continue
            session.prepare_handler(registry.handler, registry.base_info, registry.handler_config)
        
        self.sessions[session_info.session_id] = session
        return session

    def create_client_session(self, session_info: SessionInfoData, client_handler: ClientHandlerBase):
        """
        创建客户端会话
        
        这是为客户端连接（如 WebRTC）创建会话的入口方法。
        
        执行步骤：
        1. 检查会话是否已存在（目前不支持一个会话多个客户端）
        2. 创建基础会话（不包含 ClientHandler）
        3. 查找并准备 ClientHandler
        4. 返回会话和 Handler 环境
        
        参数：
            session_info: 会话信息
            client_handler: 客户端 Handler 实例
        
        返回：
            session: 会话实例
            handler_env: Handler 环境（包含上下文和数据接收器）
        
        注意：目前不支持一个会话中有多个客户端
        """
        # TODO: 目前一个会话中不允许有多个客户端
        if session_info.session_id in self.sessions:
            msg = f"Session {session_info.session_id} already exists."
            raise RuntimeError(msg)

        # 创建基础会话
        session = self._create_session(session_info, {}, {})

        # 查找 ClientHandler 的注册信息
        registry = self.handler_manager.find_client_handler(client_handler)
        if registry is None:
            raise RuntimeError(f"client handler {client_handler} not found")

        # 为 ClientHandler 准备环境
        handler_env = session.prepare_handler(client_handler, registry.base_info, registry.handler_config)
        return session, handler_env

    def stop_session(self, session_id: str):
        """
        停止并销毁会话
        
        执行步骤：
        1. 从会话字典中移除会话
        2. 调用会话的 stop 方法清理资源
        
        参数：
            session_id: 要停止的会话 ID
        """
        session = self.sessions.pop(session_id)
        if session is None:
            logger.error(f"Session {session_id} is not found.")
            return
        session.stop()
    
    def shutdown(self):
        """
        关闭聊天引擎
        
        执行步骤：
        1. 记录关闭日志
        2. 销毁 Handler 管理器（释放所有 Handler 资源）
        
        注意：这会清理所有加载的模型、关闭所有连接等
        """
        logger.info("Shutting down chat engine...")
        self.handler_manager.destroy()
