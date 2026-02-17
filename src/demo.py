"""
OpenAvatarChat Demo 启动脚本

该脚本是项目的主入口，负责：
1. 解析命令行参数
2. 加载配置文件
3. 初始化聊天引擎
4. 启动 FastAPI + Uvicorn 服务器

主要组件：
- ChatEngine: 核心聊天引擎，管理所有 handlers 和会话
- FastAPI: 提供 HTTP API 服务
- Uvicorn: ASGI 服务器
"""

from chat_engine.chat_engine import ChatEngine
import os
import argparse
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from engine_utils.directory_info import DirectoryInfo
from service.service_utils.logger_utils import config_loggers
from service.service_utils.service_config_loader import load_configs
from service.service_utils.ssl_helpers import create_ssl_context

# 将项目根目录添加到 Python 路径
project_dir = DirectoryInfo.get_project_dir()
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)


def parse_args():
    """
    解析命令行参数
    
    参数说明：
    - --host: 服务监听地址（如 0.0.0.0 或 localhost）
    - --port: 服务监听端口（如 8000）
    - --config: 配置文件路径，指定使用哪个 YAML 配置文件
    - --env: 配置文件中的环境名称（如 default, production 等）
    
    返回：
        解析后的命令行参数对象
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, help="service host address")
    parser.add_argument("--port", type=int, help="service host port")
    parser.add_argument("--config", type=str, default="config/chat_with_openai_compatible_bailian_cosyvoice.yaml", help="config file to use")
    parser.add_argument("--env", type=str, default="default", help="environment to use in config file")
    return parser.parse_args()

import torch
# 保存原始的 torch.load 函数
_original_torch_load = torch.load

def patched_torch_load(*args, **kwargs):
    """
    修补 torch.load 函数
    
    PyTorch 2.0+ 默认启用 weights_only=True 以提高安全性，
    但某些旧模型可能不兼容。这个补丁确保默认使用 weights_only=False
    以保持向后兼容性。
    
    注意：这会降低安全性，仅在信任模型来源时使用。
    """
    if 'weights_only' not in kwargs or kwargs['weights_only'] != True:
        kwargs['weights_only'] = False
    return _original_torch_load(*args, **kwargs)

# 替换全局的 torch.load 函数
torch.load = patched_torch_load

class OpenAvatarChatWebServer(uvicorn.Server):
    """
    自定义 Uvicorn 服务器类
    
    扩展标准的 Uvicorn 服务器，添加对 ChatEngine 的优雅关闭支持。
    在服务器关闭时，确保聊天引擎正确清理资源（如关闭会话、释放模型等）。
    """

    def __init__(self, chat_engine: ChatEngine, *args, **kwargs):
        """
        初始化服务器
        
        参数：
            chat_engine: 聊天引擎实例
            *args, **kwargs: 传递给父类 uvicorn.Server 的参数
        """
        super().__init__(*args, **kwargs)
        self.chat_engine = chat_engine
    
    async def shutdown(self, sockets=None):
        """
        优雅关闭服务器
        
        在服务器关闭前，先关闭聊天引擎以确保：
        1. 所有活动会话被正确终止
        2. 模型资源被释放
        3. 临时文件被清理
        4. 连接被正确关闭
        """
        logger.info("Start normal shutdown process")
        self.chat_engine.shutdown()
        await super().shutdown(sockets)


def setup_app():
    """
    设置 FastAPI 应用
    
    创建并配置：
    1. FastAPI 应用
    2. CORS 中间件（支持前后端分离）
    
    返回：
        app: FastAPI 应用实例
    """
    app = FastAPI(
        title="OpenAvatarChat API",
        description="数字人对话系统 API",
        version="1.0.0"
    )

    # 配置 CORS 中间件，支持前后端分离
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应配置具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


def main():
    """
    主函数 - 应用启动入口
    
    执行流程：
    1. 解析命令行参数
    2. 加载配置文件（日志配置、服务配置、引擎配置）
    3. 配置 ModelScope 缓存路径（用于模型下载）
    4. 初始化日志系统
    5. 创建聊天引擎实例
    6. 设置 Demo UI 界面
    7. 初始化聊天引擎（加载模型、注册 handlers）
    8. 创建 SSL 上下文（如果配置了 HTTPS）
    9. 启动 Uvicorn 服务器
    """
    # 1. 解析命令行参数
    args = parse_args()
    # 2. 加载配置文件
    logger_config, service_config, engine_config = load_configs(args)

    # 3. 设置 ModelScope 的默认下载地址
    # 如果 model_root 是相对路径，将其设置为项目目录下的路径
    if not os.path.isabs(engine_config.model_root):
        os.environ['MODELSCOPE_CACHE'] = os.path.join(DirectoryInfo.get_project_dir(),
                                                      engine_config.model_root.replace('models', ''))

    # 4. 配置日志系统
    config_loggers(logger_config)
    
    # 5. 创建聊天引擎实例
    chat_engine = ChatEngine()
    
    # 6. 创建 FastAPI 应用
    app = setup_app()

    # 7. 初始化聊天引擎
    # 这一步会：
    # - 加载所有配置的 handlers
    # - 初始化模型
    # - 注册 API 路由
    # - 设置 WebRTC 连接
    chat_engine.initialize(engine_config, app=app)

    # 8. 创建 SSL 上下文（用于 HTTPS）
    ssl_context = create_ssl_context(args, service_config)

    # 9. 配置并启动 Uvicorn 服务器
    uvicorn_config = uvicorn.Config(app, host=service_config.host, port=service_config.port, **ssl_context)
    server = OpenAvatarChatWebServer(chat_engine, uvicorn_config)
    server.run()


if __name__ == "__main__":
    """
    脚本入口点
    
    直接运行此脚本时执行 main() 函数。
    
    示例用法：
        python src/demo.py --config config/chat_with_lam.yaml --host 0.0.0.0 --port 8000
    """
    main()
