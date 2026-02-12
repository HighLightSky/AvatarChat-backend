# OpenAvatarChat 项目结构文档

## 📋 项目概述

**项目名称**: OpenAvatarChat  
**版本**: 0.5.1  
**描述**: 模块化的交互数字人对话实现，支持在单台PC上运行完整功能  
**Python版本**: >=3.11.7, <3.12  

### 核心特性
- 🎭 多模态语言模型支持（文本、音频、视频）
- 🧩 模块化设计，可灵活替换组件
- 🎨 支持多种数字人渲染方式（LAM、LiteAvatar、MuseTalk）
- 🔊 支持多种语音识别和合成方案
- 🤖 支持多种大语言模型接入

---

## 📁 根目录结构

```
OpenAvatarChat/
├── .git/                    # Git版本控制目录
├── .venv/                   # Python虚拟环境
├── assets/                  # 静态资源文件
├── build/                   # 构建输出目录
├── config/                  # 配置文件目录 ⭐
├── coturn-data/            # TURN服务器配置
├── docs/                    # 文档目录
├── logs/                    # 日志文件目录
├── models/                  # AI模型存储目录 ⭐
├── resource/                # 资源文件（如数字人素材）
├── scripts/                 # 工具脚本目录 ⭐
├── src/                     # 源代码目录 ⭐⭐⭐
├── ssl_certs/              # SSL证书目录
├── tests/                   # 测试代码目录
├── .env                     # 环境变量配置 ⭐
├── pyproject.toml          # 项目依赖配置 ⭐
├── README.md               # 项目说明文档
└── start_lam.bat           # LAM模式启动脚本
```

---

## 🔧 核心目录详解

### 1. `config/` - 配置文件目录

存放不同运行模式的配置文件，每个配置文件定义了一套完整的数字人对话方案。

```
config/
├── chat_with_lam.yaml                                    # LAM 3D数字人模式
├── chat_with_qwen_omni.yaml                             # Qwen-Omni多模态模式
├── chat_with_minicpm.yaml                               # MiniCPM-o多模态模式
├── chat_with_openai_compatible.yaml                     # OpenAI兼容API + 本地TTS
├── chat_with_openai_compatible_edge_tts.yaml           # OpenAI API + Edge TTS
├── chat_with_openai_compatible_bailian_cosyvoice.yaml  # 百炼API全云端方案
└── chat_with_openai_compatible_bailian_cosyvoice_musetalk.yaml  # MuseTalk数字人
```

**配置文件结构**:
- `logger`: 日志配置
- `service`: 服务配置（端口、SSL证书等）
- `chat_engine`: 核心引擎配置
  - `handler_configs`: 各个Handler的配置

---

### 2. `src/` - 源代码目录

#### 2.1 `src/demo.py` - 程序入口
主程序启动文件，负责：
- 加载配置
- 初始化聊天引擎
- 启动Web服务

#### 2.2 `src/chat_engine/` - 聊天引擎核心

```
chat_engine/
├── chat_engine.py          # 聊天引擎主类
├── common/                 # 公共基类
│   ├── handler_base.py            # Handler基类
│   ├── client_handler_base.py     # 客户端Handler基类
│   └── engine_channel_type.py     # 通道类型定义
├── contexts/               # 上下文管理
│   ├── handler_context.py         # Handler上下文
│   └── session_context.py         # 会话上下文
├── core/                   # 核心功能
│   ├── chat_session.py            # 会话管理
│   └── handler_manager.py         # Handler管理器
└── data_models/            # 数据模型
    ├── chat_data/                 # 聊天数据模型
    ├── runtime_data/              # 运行时数据模型
    ├── chat_data_type.py          # 数据类型定义
    ├── chat_signal.py             # 信号定义
    └── session_info_data.py       # 会话信息
```

**核心职责**:
- 管理对话流程
- 协调各个Handler之间的数据流转
- 处理会话生命周期

#### 2.3 `src/handlers/` - 模块化Handler系统 ⭐⭐⭐

这是项目最核心的部分，采用插件化架构，每个Handler负责一个特定功能。

##### 2.3.1 `handlers/vad/` - 语音活动检测

```
vad/
└── silerovad/
    ├── vad_handler_silero.py      # Silero VAD实现
    ├── silero_vad/                # Silero VAD模型
    └── pyproject.toml             # 依赖配置
```

**功能**: 检测用户何时开始/结束说话

**关键参数**:
- `speaking_threshold`: 说话检测阈值
- `start_delay`: 开始延迟
- `end_delay`: 结束延迟（影响断句）
- `buffer_look_back`: 回溯缓冲

##### 2.3.2 `handlers/asr/` - 语音识别

```
asr/
└── sensevoice/
    ├── asr_handler_sensevoice.py  # SenseVoice ASR实现
    └── pyproject.toml             # 依赖配置
```

**功能**: 将用户语音转换为文字

**支持模型**: SenseVoice (iic/SenseVoiceSmall)

##### 2.3.3 `handlers/llm/` - 大语言模型

```
llm/
├── openai_compatible/             # OpenAI兼容API
│   ├── llm_handler_openai_compatible.py
│   └── chat_history_manager.py    # 对话历史管理
├── minicpm/                       # MiniCPM-o多模态模型
│   ├── llm_handler_minicpm.py
│   └── pyproject.toml
├── qwen_omni/                     # Qwen-Omni多模态模型
│   └── llm_handler_qwen_omni.py
└── dify/                          # Dify工作流集成
    └── llm_handler_dify.py
```

**功能**: 理解用户意图并生成回复

**支持方案**:
- OpenAI兼容API（百炼、Ollama、Gemini等）
- MiniCPM-o本地推理
- Qwen-Omni实时语音对话
- Dify工作流

##### 2.3.4 `handlers/tts/` - 语音合成

```
tts/
├── bailian_tts/                   # 百炼CosyVoice API
│   ├── tts_handler_cosyvoice_bailian.py
│   └── pyproject.toml
├── cosyvoice/                     # CosyVoice本地推理
│   ├── tts_handler_cosyvoice.py
│   ├── cosyvoice_processor.py
│   ├── CosyVoice/                # CosyVoice源码
│   └── pyproject.toml
└── edgetts/                       # 微软Edge TTS
    ├── tts_handler_edgetts.py
    └── pyproject.toml
```

**功能**: 将文字转换为语音

**支持方案**:
- 百炼CosyVoice API（云端）
- CosyVoice本地推理
- Edge TTS（免费云端）

##### 2.3.5 `handlers/avatar/` - 数字人渲染

```
avatar/
├── lam/                           # LAM 3D数字人
│   ├── avatar_handler_lam_audio2expression.py
│   ├── LAM_Audio2Expression/     # LAM源码
│   ├── assets/                   # 资产文件
│   └── pyproject.toml
├── liteavatar/                    # LiteAvatar 2D数字人
│   ├── avatar_handler_liteavatar.py
│   ├── avatar_processor.py
│   ├── liteavatar_worker_manager.py
│   ├── algo/                     # 算法实现
│   ├── media/                    # 媒体处理
│   └── pyproject.toml
└── musetalk/                      # MuseTalk 2D数字人
    ├── avatar_handler_musetalk.py
    ├── avatar_musetalk_algo.py
    ├── MuseTalk/                 # MuseTalk源码
    └── pyproject.toml
```

**功能**: 根据语音生成数字人动画

**支持方案**:
- **LAM**: 3D高保真数字人，端侧渲染
- **LiteAvatar**: 2D轻量级数字人，支持GPU/CPU
- **MuseTalk**: 2D数字人，支持自定义形象

##### 2.3.6 `handlers/client/` - 客户端渲染

```
client/
├── rtc_client/                    # WebRTC服务端渲染
│   ├── client_handler_rtc.py
│   └── frontend/                 # 前端资源
└── h5_rendering_client/           # H5端侧渲染（LAM专用）
    ├── client_handler_lam.py
    └── lam_samples/              # LAM示例资产
```

**功能**: 管理客户端连接和视频流传输

**渲染方式**:
- **服务端渲染**: 数字人在服务器渲染，通过WebRTC传输
- **端侧渲染**: 数字人在浏览器渲染（LAM专用）

#### 2.4 `src/engine_utils/` - 工具库

```
engine_utils/
├── directory_info.py       # 目录信息管理
├── general_slicer.py       # 通用切片器
├── inspect_utils.py        # 检查工具
├── interval_counter.py     # 间隔计数器
├── media_utils.py          # 媒体处理工具
├── singleton.py            # 单例模式
├── time_utils.py           # 时间工具
└── components_builder/     # 组件构建器
```

**功能**: 提供通用工具函数和辅助类

#### 2.5 `src/service/` - Web服务

```
service/
├── rtc_service/            # WebRTC服务
├── service_data_models/    # 服务数据模型
└── service_utils/          # 服务工具
    ├── service_config_loader.py   # 配置加载器
    └── logger_utils.py            # 日志工具
```

**功能**: 提供HTTP/WebRTC服务接口

#### 2.6 `src/third_party/` - 第三方库

```
third_party/
└── gradio_webrtc_videochat/
    └── dist/
        └── fastrtc-0.0.28.dev0-py3-none-any.whl
```

**功能**: 存放定制的第三方库

---

### 3. `models/` - AI模型存储

```
models/
├── LAM_audio2exp/                 # LAM音频驱动模型
│   └── pretrained_models/
│       └── lam_audio2exp_streaming/
├── wav2vec2-base-960h/            # Wav2Vec2特征提取模型
├── liteavatar/                    # LiteAvatar模型（运行时下载）
├── musetalk/                      # MuseTalk模型（运行时下载）
└── iic/                           # SenseVoice模型（运行时下载）
    └── SenseVoiceSmall/
```

**说明**: 
- 部分模型需要手动下载
- 部分模型首次运行时自动下载
- 模型文件较大，建议使用Git LFS

---

### 4. `scripts/` - 工具脚本

```
scripts/
├── compile_requirements.sh         # 编译依赖
├── create_ssl_certs.sh            # 创建SSL证书
├── download_avatar_model.py       # 下载数字人模型
├── download_liteavatar_weights.sh # 下载LiteAvatar权重
├── download_MiniCPM-o_2.6.sh     # 下载MiniCPM模型
├── download_MiniCPM-o_2.6-int4.sh # 下载MiniCPM量化模型
├── download_musetalk_weights.sh   # 下载MuseTalk权重
├── post_config_install.sh         # 配置后安装脚本
├── pre_config_install.sh          # 配置前安装脚本
└── setup_coturn.sh                # 设置TURN服务器
```

**功能**: 提供各种自动化脚本

---

### 5. `resource/` - 资源文件

```
resource/
└── avatar/
    └── liteavatar/                # LiteAvatar数字人素材
        └── [各种数字人形象]/
```

**功能**: 存放数字人形象、音频等资源文件

---

## 🔄 数据流程图

```
用户语音输入
    ↓
[VAD] 语音活动检测 → 检测说话开始/结束
    ↓
[ASR] 语音识别 → 转换为文字
    ↓
[LLM] 大语言模型 → 理解并生成回复文字
    ↓
[TTS] 语音合成 → 转换为语音
    ↓
[Avatar] 数字人驱动 → 生成口型和表情动画
    ↓
[Client] 客户端渲染 → 显示数字人视频
    ↓
用户看到数字人回复
```

---

## 🎯 Handler加载机制

1. **配置驱动**: 根据配置文件中的`handler_configs`加载对应Handler
2. **动态加载**: 使用Python的`importlib`动态导入Handler模块
3. **依赖管理**: 每个Handler有独立的`pyproject.toml`管理依赖
4. **按需安装**: 只安装配置中启用的Handler的依赖

---

## 📦 依赖管理

### 核心依赖 (pyproject.toml)
- **Web框架**: FastAPI, Gradio, Uvicorn
- **WebRTC**: aiortc, fastrtc
- **深度学习**: PyTorch, torchvision, torchaudio
- **音频处理**: librosa, soundfile
- **配置管理**: dynaconf, pydantic
- **日志**: loguru

### Handler依赖 (各Handler的pyproject.toml)
- **SenseVoice**: funasr
- **LAM**: transformers, addict
- **LiteAvatar**: onnxruntime, opencv
- **MuseTalk**: mmcv, face-alignment
- **CosyVoice**: WeTextProcessing, matcha-tts
- **百炼API**: dashscope

---

## 🚀 启动流程

1. **加载配置** (`demo.py`)
   - 读取YAML配置文件
   - 加载环境变量（.env）

2. **初始化引擎** (`chat_engine.py`)
   - 创建Handler管理器
   - 根据配置加载各个Handler

3. **启动服务** (`service/`)
   - 启动Gradio Web界面
   - 建立WebRTC连接
   - 开始接收用户输入

4. **处理对话**
   - VAD检测语音
   - ASR识别文字
   - LLM生成回复
   - TTS合成语音
   - Avatar生成动画
   - Client推送视频流

---

## 🔐 配置文件说明

### .env 文件
```bash
# 百炼API Key
DASHSCOPE_API_KEY=sk-your-api-key-here
```

### YAML配置文件结构
```yaml
default:
  logger:
    log_level: "INFO"
  
  service:
    host: "0.0.0.0"
    port: 8282
    cert_file: "ssl_certs/localhost.crt"
    cert_key: "ssl_certs/localhost.key"
  
  chat_engine:
    model_root: "models"
    concurrent_limit: 5
    handler_search_path:
      - "src/handlers"
    
    handler_configs:
      # 各个Handler的配置
      HandlerName:
        enabled: True
        module: "path/to/handler"
        # Handler特定参数
```

---

## 📝 预置配置模式对比

| 配置文件 | ASR | LLM | TTS | Avatar | 特点 |
|---------|-----|-----|-----|--------|------|
| chat_with_lam.yaml | SenseVoice | API | 百炼API | LAM | 3D高保真，端侧渲染 |
| chat_with_qwen_omni.yaml | Qwen-Omni | Qwen-Omni | Qwen-Omni | LiteAvatar | 端到端语音对话 |
| chat_with_minicpm.yaml | MiniCPM-o | MiniCPM-o | MiniCPM-o | LiteAvatar | 本地多模态 |
| chat_with_openai_compatible.yaml | SenseVoice | API | CosyVoice | LiteAvatar | 混合方案 |
| chat_with_openai_compatible_edge_tts.yaml | SenseVoice | API | Edge TTS | LiteAvatar | 免费TTS |
| chat_with_openai_compatible_bailian_cosyvoice.yaml | SenseVoice | API | 百炼API | LiteAvatar | 全云端 |
| chat_with_openai_compatible_bailian_cosyvoice_musetalk.yaml | SenseVoice | API | 百炼API | MuseTalk | 自定义形象 |

---

## 🛠️ 开发指南

### 添加新的Handler

1. 在`src/handlers/`对应类型目录下创建新Handler
2. 继承对应的基类（如`HandlerBase`）
3. 实现必要的方法（`load`, `process`等）
4. 创建`pyproject.toml`定义依赖
5. 在配置文件中添加Handler配置

### Handler基类方法

```python
class HandlerBase:
    def load(self, config):
        """加载Handler，初始化模型"""
        pass
    
    def process(self, data):
        """处理数据"""
        pass
    
    def unload(self):
        """卸载Handler，释放资源"""
        pass
```

---

## 📊 性能指标

- **平均响应延迟**: ~2.2秒（i9-13900KF + RTX 4090）
- **LiteAvatar帧率**: 25-30 FPS（GPU）/ 20-25 FPS（CPU）
- **LAM帧率**: 30+ FPS（端侧渲染）
- **MuseTalk帧率**: 20-25 FPS（GPU）

---

## 🔗 相关链接

- **项目主页**: https://github.com/HumanAIGC-Engineering/OpenAvatarChat
- **在线Demo**: https://modelscope.cn/studios/HumanAIGC-Engineering/open-avatar-chat
- **文档**: https://github.com/HumanAIGC-Engineering/OpenAvatarChat/blob/main/README.md
- **前端仓库**: https://github.com/HumanAIGC-Engineering/OpenAvatarChat-WebUI

---

## 📄 许可证

本项目采用开源许可证，详见 LICENSE 文件。

---

**文档版本**: 1.0  
**更新日期**: 2026-02-12  
**维护者**: OpenAvatarChat Team
