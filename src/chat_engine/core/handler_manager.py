"""
HandlerManager - Handler 管理器

负责 Handler 的完整生命周期管理：
1. 搜索和发现 Handler 模块
2. 动态加载 Handler 类
3. 注册和配置 Handler 实例
4. 管理 Handler 的加载和销毁

Handler 加载流程：
┌─────────────────────────────────────────────────────────────┐
│ 1. initialize() - 初始化阶段                                 │
│    ├─ 读取配置文件中的 handler_configs                       │
│    ├─ 设置 handler_search_path（Handler 搜索路径）           │
│    ├─ 遍历每个启用的 Handler 配置                            │
│    │   ├─ 在搜索路径中查找 Handler 模块文件                  │
│    │   ├─ 使用 importlib 动态导入模块                        │
│    │   ├─ 通过反射查找 HandlerBase 子类                      │
│    │   ├─ 实例化 Handler 类                                  │
│    │   └─ 调用 register_handler() 注册 Handler               │
│    └─ 保存模块和类的引用到 handler_modules                   │
│                                                               │
│ 2. register_handler() - 注册阶段                             │
│    ├─ 创建 HandlerRegistry 注册表                            │
│    ├─ 设置 handler_root（Handler 模块所在目录）              │
│    ├─ 调用 handler.on_before_register()                      │
│    ├─ 调用 handler.get_handler_info() 获取 Handler 信息      │
│    ├─ 验证和解析 Handler 配置                                │
│    └─ 保存到 handler_registries                              │
│                                                               │
│ 3. load_handlers() - 加载阶段                                │
│    ├─ 获取所有启用的 Handler                                 │
│    ├─ 遍历每个 Handler                                       │
│    │   ├─ 调用 handler.load() 加载模型和资源                 │
│    │   └─ 记录加载耗时                                       │
│    └─ 对于 ClientHandler                                     │
│        └─ 调用 on_setup_app() 设置 Web 接口                  │
│                                                               │
│ 4. destroy() - 销毁阶段                                      │
│    └─ 调用每个 Handler 的 destroy() 方法释放资源             │
└─────────────────────────────────────────────────────────────┘
"""

import importlib
import inspect
import os.path
import sys
import time
import weakref
from dataclasses import dataclass, field
from inspect import isclass, isabstract
from types import ModuleType
from typing import Optional, Dict, Tuple

import gradio
from fastapi import FastAPI
from loguru import logger

from chat_engine.common.client_handler_base import ClientHandlerBase
from chat_engine.common.handler_base import HandlerBaseInfo, HandlerBase
from chat_engine.data_models.chat_engine_config_data import HandlerBaseConfigModel, ChatEngineConfigModel
from engine_utils.directory_info import DirectoryInfo


@dataclass
class HandlerRegistry:
    """
    Handler 注册表
    
    存储单个 Handler 的完整信息：
    - base_info: Handler 基本信息（名称、优先级等）
    - handler: Handler 实例
    - handler_config: Handler 配置对象
    """
    base_info: Optional[HandlerBaseInfo] = field(default=None)
    handler: Optional[HandlerBase] = field(default=None)
    handler_config: Optional[HandlerBaseConfigModel] = field(default=None)


class HandlerManager:
    """
    Handler 管理器
    
    核心职责：
    1. 动态发现和加载 Handler 模块
    2. 管理 Handler 的注册表
    3. 处理 Handler 的配置和初始化
    4. 提供 Handler 查询接口
    """
    def __init__(self, engine):
        # Handler 模块字典：{模块路径: (模块对象, Handler类)}
        self.handler_modules: Dict[str, Tuple[ModuleType, type[HandlerBase]]] = {}
        # Handler 注册表：{handler名称: HandlerRegistry}
        self.handler_registries: Dict[str, HandlerRegistry] = {}
        # Handler 配置字典：{handler名称: 配置字典}
        self.handler_configs: Dict[str, Dict] = {}
        self.concurrent_limit = 1  # 并发限制
        self.search_path = []  # Handler 搜索路径列表

        # 使用弱引用避免循环引用
        self.engine_ref = weakref.ref(engine)

    def initialize(self, engine_config: ChatEngineConfigModel):
        """
        初始化 Handler 管理器
        
        这是 Handler 加载的第一阶段，执行步骤：
        
        1. 设置并发限制
        2. 添加所有 Handler 搜索路径
        3. 加载所有 Handler 配置
        4. 遍历每个启用的 Handler：
           a. 验证配置格式
           b. 在搜索路径中查找 Handler 模块文件
           c. 使用 importlib 动态导入模块
           d. 通过反射查找 HandlerBase 子类
           e. 实例化 Handler 并注册
        
        Handler 发现机制：
        - 从配置文件读取 module 路径（如 "handlers/vad/silerovad/vad_handler_silero"）
        - 在 handler_search_path 中查找对应的 .py 文件
        - 动态导入模块并查找 HandlerBase 的非抽象子类
        
        参数：
            engine_config: 引擎配置对象
        """
        self.concurrent_limit = engine_config.concurrent_limit
        
        # 添加所有搜索路径
        for search_path in engine_config.handler_search_path:
            self.add_search_path(search_path)
        
        # 加载所有 Handler 配置
        for handler_name, handler_config in engine_config.handler_configs.items():
            self.handler_configs[handler_name] = handler_config
        
        logger.info(f"Use handler search path: {self.search_path}")
        
        # 遍历并加载每个 Handler
        for handler_name, raw_config in self.handler_configs.items():
            # 验证配置格式
            try:
                handler_config = HandlerBaseConfigModel.model_validate(raw_config)
            except Exception as e:
                logger.error(f"Failed to parse handler config for {handler_name}: {e}")
                continue
            
            # 跳过未启用的 Handler
            if not handler_config.enabled:
                continue
            if handler_config.module is None:
                logger.warning(f"Handler {handler_name} has no module specified, skipping.")
                continue
            
            # 在搜索路径中查找 Handler 模块文件
            module_path = None
            module_input_path = None
            for search_path in self.search_path:
                find_path = os.path.join(search_path, f"{handler_config.module}.py")
                if os.path.exists(find_path):
                    module_path = find_path
                    # 将文件路径转换为 Python 模块路径（如 handlers.vad.silerovad.vad_handler_silero）
                    module_input_path = handler_config.module.replace("\/", ".").replace("/", ".")
                    break
            
            if module_path is None:
                logger.error(f"Handler {handler_config.module} not found in search path.")
                raise ValueError(f"Handler {handler_config.module} not found in search path.")
            
            # 动态导入模块
            try:
                logger.info(f"Try to load {module_input_path}")
                module = importlib.import_module(module_input_path)
            except Exception:
                logger.error(f"Failed to import handler module {handler_config.module}")
                raise
            
            # 通过反射查找 HandlerBase 子类
            handler_class = None
            for name, obj in inspect.getmembers(module):
                if not isclass(obj):
                    continue
                if isabstract(obj):  # 跳过抽象类
                    continue
                if issubclass(obj, HandlerBase):
                    handler_class = obj
                    break
            
            if handler_class is None:
                logger.error(f"Handler module {handler_config.module} does not contain a HandlerBase subclass.")
                raise ValueError(f"Handler module {handler_config.module} does not contain a HandlerBase subclass.")
            
            # 保存模块和类的引用
            self.handler_modules[handler_config.module] = module, handler_class
            # 实例化并注册 Handler
            self.register_handler(handler_name, handler_class())

    def add_search_path(self, path: str):
        """
        添加 Handler 搜索路径
        
        执行步骤：
        1. 将相对路径转换为绝对路径
        2. 验证路径是否为目录
        3. 添加到搜索路径列表
        4. 同时添加到 sys.path（用于 Python 模块导入）
        
        参数：
            path: 搜索路径（可以是相对或绝对路径）
        """
        # 处理相对路径
        if not os.path.isabs(path):
            if os.path.isdir(path):
                path = os.path.abspath(path)
            else:
                path = os.path.join(DirectoryInfo.get_project_dir(), path)
        
        # 验证路径
        if not os.path.isdir(path):
            logger.warning(f"Path {path} is not a directory, it is not added to search path.")
            return
        
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        
        # 添加到搜索路径
        if path not in self.search_path:
            self.search_path.append(path)
            # 同时添加到 Python 模块搜索路径
            if path not in sys.path:
                sys.path.append(path)

    def register_handler(self, name: str, handler: HandlerBase):
        """
        注册 Handler
        
        这是 Handler 加载的第二阶段，执行步骤：
        
        1. 创建或获取 HandlerRegistry
        2. 设置 Handler 的根目录（handler_root）
        3. 设置 Handler 的引擎引用
        4. 调用 Handler 的生命周期钩子：
           - on_before_register(): 注册前的准备工作
           - get_handler_info(): 获取 Handler 信息（名称、配置模型等）
        5. 验证和解析 Handler 配置
        6. 保存到注册表
        
        handler_root 的作用：
        - 指向 Handler 模块所在的目录
        - Handler 可以用它来定位相对资源（如模型文件、配置文件）
        - 例如：handlers/vad/silerovad/ 目录
        
        参数：
            name: Handler 名称（来自配置文件）
            handler: Handler 实例
        """
        # 获取或创建注册表
        registry = self.handler_registries.get(name, None)
        if registry is None:
            registry = HandlerRegistry()
            self.handler_registries[name] = registry
        
        # 设置 Handler 的根目录
        handler_module = inspect.getmodule(type(handler))
        handler_root = os.path.split(handler_module.__file__)[0]
        handler.handler_root = handler_root
        
        # 设置引擎引用（弱引用）
        handler.engine = self.engine_ref
        
        if registry.base_info is None:
            # 调用注册前钩子
            handler.on_before_register()
            
            # 获取 Handler 信息
            base_info = handler.get_handler_info()
            base_info.name = name
            
            # 获取原始配置
            raw_config = self.handler_configs.get(name, {})
            
            # 验证配置模型
            if not issubclass(base_info.config_model, HandlerBaseConfigModel):
                logger.error(f"Handler {name} provides invalid config model {base_info.config_model}")
                raise ValueError(f"Handler {name} provides invalid config model {base_info.config_model}")
            
            # 解析配置
            config: HandlerBaseConfigModel = base_info.config_model.model_validate(raw_config)
            config.concurrent_limit = self.concurrent_limit
            
            # 保存到注册表
            registry.base_info = base_info
            registry.handler = handler
            registry.handler_config = config
            
            logger.info(f"Registered handler {name}({type(handler)}) with config: {config}")

    def load_handlers(self, engine_config: ChatEngineConfigModel,
                      app: Optional[FastAPI] = None,
                      ui: Optional[gradio.blocks.Block] = None,
                      parent_block: Optional[gradio.blocks.Block] = None):
        """
        加载所有 Handler
        
        这是 Handler 加载的第三阶段，执行步骤：
        
        1. 获取所有启用的 Handler（按优先级排序）
        2. 遍历每个 Handler：
           - 调用 handler.load() 加载模型和资源
           - 记录加载耗时
        3. 对于 ClientHandler（如 WebRTC Handler）：
           - 调用 on_setup_app() 设置 Web 接口
           - 注册 API 路由和 UI 组件
        
        load() 方法的作用：
        - 加载深度学习模型（如 VAD 模型、TTS 模型）
        - 初始化外部服务连接（如 OpenAI API）
        - 准备运行时资源
        
        ClientHandler 的特殊处理：
        - ClientHandler 负责与客户端通信（WebRTC、WebSocket 等）
        - 需要注册 HTTP API 路由和 Gradio UI 组件
        - 在所有其他 Handler 加载完成后才设置
        
        参数：
            engine_config: 引擎配置
            app: FastAPI 应用（用于注册 API）
            ui: Gradio UI 实例（用于添加组件）
            parent_block: Gradio 父容器
        """
        # 获取所有启用的 Handler
        enabled_handlers = self.get_enabled_handler_registries()
        client_handlers = []
        
        # 加载所有 Handler
        for registry in enabled_handlers:
            # 收集 ClientHandler，稍后处理
            if isinstance(registry.handler, ClientHandlerBase):
                client_handlers.append(registry)
            
            # 调用 load() 方法加载资源
            load_start = time.monotonic()
            registry.handler.load(engine_config, registry.handler_config)
            dur_load = time.monotonic() - load_start
            logger.info(f"Handler {registry.base_info.name} loaded in {round(dur_load * 1e3)} milliseconds")
        
        # 设置 ClientHandler 的 Web 接口
        if app is not None or ui is not None:
            for registry in client_handlers:
                setup_start = time.monotonic()
                registry.handler.on_setup_app(app, ui, parent_block)
                dur_setup = time.monotonic() - setup_start
                logger.info(f"Setup client handler {registry.base_info.name} loaded in {round(dur_setup * 1e3)} milliseconds")

    def get_enabled_handler_registries(self, order_by_priority=True):
        """
        获取所有启用的 Handler 注册表
        
        参数：
            order_by_priority: 是否按加载优先级排序
        
        返回：
            启用的 Handler 注册表列表
        
        优先级排序的作用：
        - 确保依赖关系正确（如 VAD 需要在 ASR 之前加载）
        - 优化资源分配顺序
        """
        result = []
        for handler_name, registry in self.handler_registries.items():
            if registry.handler is None or registry.handler_config is None:
                continue
            if not registry.handler_config.enabled:
                continue
            result.append(registry)
        
        # 按优先级排序
        if order_by_priority:
            result.sort(key=lambda x: x.base_info.load_priority)
        return result

    def find_client_handler(self, handler):
        """
        查找指定的 ClientHandler 注册表
        
        用于在创建客户端会话时查找对应的 Handler 配置。
        
        参数：
            handler: ClientHandler 实例
        
        返回：
            对应的 HandlerRegistry，如果未找到则返回 None
        """
        if handler is None:
            return None
        for handler_name, registry in self.handler_registries.items():
            if registry.handler is None or registry.handler_config is None:
                continue
            if not registry.handler_config.enabled:
                continue
            if isinstance(registry.handler, ClientHandlerBase) and registry.handler is handler:
                return registry

    def destroy(self):
        """
        销毁所有 Handler
        
        这是 Handler 生命周期的最后阶段，执行步骤：
        
        1. 遍历所有启用的 Handler
        2. 调用 handler.destroy() 方法
        3. 释放资源：
           - 卸载深度学习模型
           - 关闭外部连接
           - 清理临时文件
           - 释放 GPU 内存
        
        在应用关闭时调用，确保资源正确释放。
        """
        for handler_name, registry in self.handler_registries.items():
            if registry.handler is None or registry.handler_config is None:
                continue
            if not registry.handler_config.enabled:
                continue
            logger.info(f"Destroying handler {handler_name}")
            registry.handler.destroy()
            logger.info(f"Handler {handler_name} destroyed")