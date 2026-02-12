# OpenAvatarChat Handler 完全指南

## 📚 目录
1. [什么是Handler？](#什么是handler)
2. [Handler的核心概念](#handler的核心概念)
3. [Handler的生命周期](#handler的生命周期)
4. [如何定义Handler](#如何定义handler)
5. [Handler能做什么](#handler能做什么)
6. [实战示例](#实战示例)
7. [最佳实践](#最佳实践)

---

## 什么是Handler？

### 定义
**Handler** 是 OpenAvatarChat 中的**可插拔功能模块**，每个Handler负责处理对话流程中的一个特定环节。

### 类比理解
把数字人对话系统想象成一条**流水线**：
- 用户说话 → **VAD Handler**（检测说话）→ **ASR Handler**（识别文字）→ **LLM Handler**（生成回复）→ **TTS Handler**（合成语音）→ **Avatar Handler**（生成动画）→ 数字人回复

每个Handler就像流水线上的一个**工作站**，专注做好一件事。

### 核心特点
✅ **模块化**: 每个Handler独立开发、独立配置  
✅ **可替换**: 可以轻松切换不同的实现（如换个TTS引擎）  
✅ **可组合**: 通过配置文件自由组合Handler  
✅ **数据驱动**: Handler之间通过标准化的数据格式通信  

---

## Handler的核心概念

### 1. Handler基类 (`HandlerBase`)

所有Handler都必须继承自 `HandlerBase` 抽象基类：

```python
from chat_engine.common.handler_base import HandlerBase

class MyHandler(HandlerBase):
    """自定义Handler"""
    pass
```

### 2. 数据类型 (`ChatDataType`)

Handler之间通过标准化的数据类型通信：

```python
class ChatDataType(Enum):
    MIC_AUDIO = "mic_audio"           # 麦克风音频
    HUMAN_AUDIO = "human_audio"       # 人类语音（经过VAD处理）
    HUMAN_TEXT = "human_text"         # 人类文字
    AVATAR_TEXT = "avatar_text"       # 数字人回复文字
    AVATAR_AUDIO = "avatar_audio"     # 数字人语音
    AVATAR_MOTION = "avatar_motion"   # 数字人动作数据
    VIDEO_FRAME = "video_frame"       # 视频帧
```

### 3. Handler信息 (`HandlerBaseInfo`)

定义Handler的基本信息：

```python
@dataclass
class HandlerBaseInfo:
    name: str                                    # Handler名称
    config_model: type[HandlerBaseConfigModel]  # 配置模型类
    client_session_delegate_class: Optional[type] = None
    load_priority: int = 0                       # 加载优先级
```

### 4. Handler详情 (`HandlerDetail`)

定义Handler的输入输出：

```python
@dataclass
class HandlerDetail:
    inputs: Dict[ChatDataType, HandlerDataInfo]   # 输入数据类型
    outputs: Dict[ChatDataType, HandlerDataInfo]  # 输出数据类型
```

### 5. Handler上下文 (`HandlerContext`)

每个会话都有独立的上下文，存储会话相关的状态：

```python
class MyHandlerContext(HandlerContext):
    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.config = None
        self.model_state = None
        # ... 其他会话状态
```

---

## Handler的生命周期

```
┌─────────────────────────────────────────────────────────┐
│                    Handler生命周期                        │
└─────────────────────────────────────────────────────────┘

1. 注册阶段（系统启动时）
   ├─ on_before_register()      # 注册前回调
   ├─ get_handler_info()        # 获取Handler信息
   └─ load()                    # 加载模型和资源

2. 会话创建阶段（用户连接时）
   ├─ create_context()          # 创建会话上下文
   ├─ start_context()           # 启动会话
   └─ get_handler_detail()      # 获取输入输出定义

3. 数据处理阶段（对话进行中）
   └─ handle()                  # 处理数据（核心方法）
      ├─ 接收输入数据
      ├─ 执行处理逻辑
      └─ yield 输出数据

4. 会话销毁阶段（用户断开时）
   └─ destroy_context()         # 清理会话资源

5. Handler销毁阶段（系统关闭时）
   └─ destroy()                 # 清理全局资源
```

---

## 如何定义Handler

### 步骤1: 创建配置模型

```python
from pydantic import BaseModel, Field
from chat_engine.data_models.chat_engine_config_data import HandlerBaseConfigModel

class MyHandlerConfig(HandlerBaseConfigModel, BaseModel):
    """Handler配置"""
    model_path: str = Field(default="models/my_model")
    threshold: float = Field(default=0.5)
    batch_size: int = Field(default=1)
```

### 步骤2: 创建上下文类

```python
from chat_engine.contexts.handler_context import HandlerContext

class MyHandlerContext(HandlerContext):
    """Handler会话上下文"""
    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.config: MyHandlerConfig = None
        self.model_state = None
        self.buffer = []
```

### 步骤3: 实现Handler类

```python
from chat_engine.common.handler_base import HandlerBase, HandlerBaseInfo, HandlerDetail
from chat_engine.data_models.chat_data_type import ChatDataType

class MyHandler(HandlerBase):
    """自定义Handler实现"""
    
    def __init__(self):
        super().__init__()
        self.model = None
    
    # 1. 返回Handler信息
    def get_handler_info(self) -> HandlerBaseInfo:
        return HandlerBaseInfo(
            name="MyHandler",
            config_model=MyHandlerConfig,
            load_priority=0
        )
    
    # 2. 加载模型和资源（系统启动时调用一次）
    def load(self, engine_config, handler_config=None):
        config = handler_config  # MyHandlerConfig实例
        # 加载模型
        self.model = load_model(config.model_path)
        logger.info(f"Loaded model from {config.model_path}")
    
    # 3. 创建会话上下文（每个用户连接时调用）
    def create_context(self, session_context, handler_config=None):
        context = MyHandlerContext(session_context.session_info.session_id)
        context.config = handler_config
        return context
    
    # 4. 启动会话（可选）
    def start_context(self, session_context, handler_context):
        # 初始化会话相关资源
        pass
    
    # 5. 定义输入输出（每个会话调用一次）
    def get_handler_detail(self, session_context, context):
        # 定义输出数据格式
        output_def = DataBundleDefinition()
        output_def.add_entry(
            DataBundleEntry.create_audio_entry("output_audio", 1, 16000)
        )
        
        return HandlerDetail(
            inputs={
                ChatDataType.HUMAN_AUDIO: HandlerDataInfo(
                    type=ChatDataType.HUMAN_AUDIO
                )
            },
            outputs={
                ChatDataType.HUMAN_TEXT: HandlerDataInfo(
                    type=ChatDataType.HUMAN_TEXT,
                    definition=output_def
                )
            }
        )
    
    # 6. 处理数据（核心方法，每次有数据时调用）
    def handle(self, context, inputs, output_definitions):
        """
        处理输入数据并生成输出
        
        Args:
            context: Handler上下文
            inputs: 输入的ChatData
            output_definitions: 输出数据定义
        
        Yields:
            ChatData: 输出数据
        """
        # 检查输入类型
        if inputs.type != ChatDataType.HUMAN_AUDIO:
            return
        
        # 获取输入数据
        audio = inputs.data.get_main_data()
        
        # 执行处理逻辑
        result = self.model.process(audio)
        
        # 构造输出数据
        output_def = output_definitions[ChatDataType.HUMAN_TEXT].definition
        output_bundle = DataBundle(output_def)
        output_bundle.set_main_data(result)
        
        # 返回输出
        output_data = ChatData(
            type=ChatDataType.HUMAN_TEXT,
            data=output_bundle
        )
        yield output_data
    
    # 7. 销毁会话上下文
    def destroy_context(self, context):
        # 清理会话资源
        context.buffer.clear()
    
    # 8. 销毁Handler（可选）
    def destroy(self):
        # 清理全局资源
        if self.model:
            del self.model
```

### 步骤4: 创建依赖配置

在Handler目录下创建 `pyproject.toml`：

```toml
[project]
name = "my-handler"
version = "0.1.0"
requires-python = ">=3.11, <3.12"
dependencies = [
    "numpy>=1.26.0",
    "torch>=2.0.0",
    # ... 其他依赖
]
```

### 步骤5: 在配置文件中启用

在 `config/my_config.yaml` 中添加：

```yaml
default:
  chat_engine:
    handler_configs:
      MyHandler:
        enabled: True
        module: "handlers/my_category/my_handler"
        model_path: "models/my_model"
        threshold: 0.5
        batch_size: 1
```

---

## Handler能做什么

### 1. 语音活动检测 (VAD Handler)

**功能**: 检测用户何时开始/结束说话

**输入**: 麦克风原始音频 (`MIC_AUDIO`)  
**输出**: 人类语音片段 (`HUMAN_AUDIO`)

**关键逻辑**:
```python
def handle(self, context, inputs, output_definitions):
    audio = inputs.data.get_main_data()
    
    # 计算语音概率
    speech_prob = self.model.predict(audio)
    
    # 状态机：检测说话开始/结束
    if speech_prob > threshold:
        if not context.is_speaking:
            context.is_speaking = True
            yield start_speech_event()
    else:
        if context.is_speaking:
            context.is_speaking = False
            yield end_speech_event()
```

**应用场景**:
- 自动断句
- 降低误触发
- 优化响应时机

---

### 2. 语音识别 (ASR Handler)

**功能**: 将语音转换为文字

**输入**: 人类语音 (`HUMAN_AUDIO`)  
**输出**: 人类文字 (`HUMAN_TEXT`)

**关键逻辑**:
```python
def handle(self, context, inputs, output_definitions):
    audio = inputs.data.get_main_data()
    
    # 累积音频直到说话结束
    context.audio_buffer.append(audio)
    
    speech_end = inputs.data.get_meta("human_speech_end", False)
    if speech_end:
        # 完整音频送入ASR模型
        full_audio = np.concatenate(context.audio_buffer)
        text = self.model.transcribe(full_audio)
        
        # 输出识别结果
        yield create_text_output(text)
        
        # 清空缓冲
        context.audio_buffer.clear()
```

**应用场景**:
- 语音转文字
- 多语言识别
- 实时字幕

---

### 3. 大语言模型 (LLM Handler)

**功能**: 理解用户意图并生成回复

**输入**: 人类文字 (`HUMAN_TEXT`)  
**输出**: 数字人回复文字 (`AVATAR_TEXT`)

**关键逻辑**:
```python
def handle(self, context, inputs, output_definitions):
    user_text = inputs.data.get_main_data()
    
    # 添加到对话历史
    context.history.append({"role": "user", "content": user_text})
    
    # 调用LLM生成回复（流式）
    for chunk in self.llm.stream_generate(context.history):
        # 实时输出每个文字片段
        yield create_text_output(chunk)
    
    # 标记回复结束
    yield create_text_output("", meta={"avatar_text_end": True})
```

**应用场景**:
- 智能对话
- 知识问答
- 任务执行

---

### 4. 语音合成 (TTS Handler)

**功能**: 将文字转换为语音

**输入**: 数字人文字 (`AVATAR_TEXT`)  
**输出**: 数字人语音 (`AVATAR_AUDIO`)

**关键逻辑**:
```python
def handle(self, context, inputs, output_definitions):
    text = inputs.data.get_main_data()
    
    # 流式合成（边生成边输出）
    if not context.synthesizer:
        context.synthesizer = create_synthesizer()
    
    # 送入文字片段
    context.synthesizer.add_text(text)
    
    # 获取生成的音频
    for audio_chunk in context.synthesizer.get_audio():
        yield create_audio_output(audio_chunk)
    
    # 检查是否结束
    text_end = inputs.data.get_meta("avatar_text_end", False)
    if text_end:
        context.synthesizer.finalize()
        context.synthesizer = None
```

**应用场景**:
- 文字转语音
- 音色克隆
- 情感表达

---

### 5. 数字人驱动 (Avatar Handler)

**功能**: 根据语音生成数字人动画

**输入**: 数字人语音 (`AVATAR_AUDIO`)  
**输出**: 数字人动作数据 (`AVATAR_MOTION`)

**关键逻辑**:
```python
def handle(self, context, inputs, output_definitions):
    audio = inputs.data.get_main_data()
    
    # 提取音频特征
    features = extract_audio_features(audio)
    
    # 生成口型和表情参数
    motion_params = self.model.generate_motion(features)
    
    # 输出动作数据
    yield create_motion_output(motion_params)
```

**应用场景**:
- 口型同步
- 表情生成
- 肢体动作

---

### 6. 客户端渲染 (Client Handler)

**功能**: 管理客户端连接和视频流传输

**输入**: 数字人动作数据 (`AVATAR_MOTION`)  
**输出**: 视频帧 (`VIDEO_FRAME`)

**关键逻辑**:
```python
def handle(self, context, inputs, output_definitions):
    motion_data = inputs.data.get_main_data()
    
    # 渲染数字人
    frame = self.renderer.render(motion_data)
    
    # 通过WebRTC发送视频帧
    yield create_video_output(frame)
```

**应用场景**:
- 视频流传输
- 实时渲染
- 多客户端管理

---

## 实战示例

### 示例1: 简单的文本过滤Handler

```python
"""
功能：过滤敏感词
输入：HUMAN_TEXT
输出：HUMAN_TEXT（过滤后）
"""

class TextFilterConfig(HandlerBaseConfigModel, BaseModel):
    banned_words: list[str] = Field(default_factory=list)

class TextFilterContext(HandlerContext):
    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.config: TextFilterConfig = None

class TextFilterHandler(HandlerBase):
    def get_handler_info(self):
        return HandlerBaseInfo(
            name="TextFilter",
            config_model=TextFilterConfig
        )
    
    def load(self, engine_config, handler_config=None):
        self.banned_words = handler_config.banned_words
        logger.info(f"Loaded {len(self.banned_words)} banned words")
    
    def create_context(self, session_context, handler_config=None):
        context = TextFilterContext(session_context.session_info.session_id)
        context.config = handler_config
        return context
    
    def start_context(self, session_context, handler_context):
        pass
    
    def get_handler_detail(self, session_context, context):
        return HandlerDetail(
            inputs={
                ChatDataType.HUMAN_TEXT: HandlerDataInfo(
                    type=ChatDataType.HUMAN_TEXT
                )
            },
            outputs={
                ChatDataType.HUMAN_TEXT: HandlerDataInfo(
                    type=ChatDataType.HUMAN_TEXT
                )
            }
        )
    
    def handle(self, context, inputs, output_definitions):
        if inputs.type != ChatDataType.HUMAN_TEXT:
            return
        
        text = inputs.data.get_main_data()
        
        # 过滤敏感词
        for word in self.banned_words:
            text = text.replace(word, "***")
        
        # 输出过滤后的文本
        output = DataBundle(output_definitions[ChatDataType.HUMAN_TEXT].definition)
        output.set_main_data(text)
        
        yield ChatData(type=ChatDataType.HUMAN_TEXT, data=output)
    
    def destroy_context(self, context):
        pass
```

**配置文件**:
```yaml
TextFilter:
  enabled: True
  module: "handlers/text/text_filter"
  banned_words: ["敏感词1", "敏感词2"]
```

---

### 示例2: 音频音量调节Handler

```python
"""
功能：调节音频音量
输入：AVATAR_AUDIO
输出：AVATAR_AUDIO（调节后）
"""

class VolumeControlConfig(HandlerBaseConfigModel, BaseModel):
    volume_scale: float = Field(default=1.0, ge=0.0, le=2.0)

class VolumeControlHandler(HandlerBase):
    def get_handler_info(self):
        return HandlerBaseInfo(
            name="VolumeControl",
            config_model=VolumeControlConfig
        )
    
    def load(self, engine_config, handler_config=None):
        self.volume_scale = handler_config.volume_scale
    
    def create_context(self, session_context, handler_config=None):
        return HandlerContext(session_context.session_info.session_id)
    
    def start_context(self, session_context, handler_context):
        pass
    
    def get_handler_detail(self, session_context, context):
        definition = DataBundleDefinition()
        definition.add_entry(
            DataBundleEntry.create_audio_entry("audio", 1, 24000)
        )
        
        return HandlerDetail(
            inputs={
                ChatDataType.AVATAR_AUDIO: HandlerDataInfo(
                    type=ChatDataType.AVATAR_AUDIO
                )
            },
            outputs={
                ChatDataType.AVATAR_AUDIO: HandlerDataInfo(
                    type=ChatDataType.AVATAR_AUDIO,
                    definition=definition
                )
            }
        )
    
    def handle(self, context, inputs, output_definitions):
        if inputs.type != ChatDataType.AVATAR_AUDIO:
            return
        
        audio = inputs.data.get_main_data()
        
        # 调节音量
        adjusted_audio = audio * self.volume_scale
        
        # 防止溢出
        adjusted_audio = np.clip(adjusted_audio, -1.0, 1.0)
        
        # 输出
        output_def = output_definitions[ChatDataType.AVATAR_AUDIO].definition
        output = DataBundle(output_def)
        output.set_main_data(adjusted_audio)
        
        yield ChatData(type=ChatDataType.AVATAR_AUDIO, data=output)
    
    def destroy_context(self, context):
        pass
```

---

### 示例3: 对话历史记录Handler

```python
"""
功能：记录对话历史到文件
输入：HUMAN_TEXT, AVATAR_TEXT
输出：无（仅记录）
"""

class HistoryLoggerConfig(HandlerBaseConfigModel, BaseModel):
    log_dir: str = Field(default="logs/conversations")

class HistoryLoggerContext(HandlerContext):
    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.log_file = None

class HistoryLoggerHandler(HandlerBase):
    def get_handler_info(self):
        return HandlerBaseInfo(
            name="HistoryLogger",
            config_model=HistoryLoggerConfig
        )
    
    def load(self, engine_config, handler_config=None):
        self.log_dir = handler_config.log_dir
        os.makedirs(self.log_dir, exist_ok=True)
    
    def create_context(self, session_context, handler_config=None):
        context = HistoryLoggerContext(session_context.session_info.session_id)
        
        # 创建会话日志文件
        log_path = os.path.join(
            self.log_dir, 
            f"{context.session_id}_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        )
        context.log_file = open(log_path, "w", encoding="utf-8")
        
        return context
    
    def start_context(self, session_context, handler_context):
        pass
    
    def get_handler_detail(self, session_context, context):
        return HandlerDetail(
            inputs={
                ChatDataType.HUMAN_TEXT: HandlerDataInfo(
                    type=ChatDataType.HUMAN_TEXT
                ),
                ChatDataType.AVATAR_TEXT: HandlerDataInfo(
                    type=ChatDataType.AVATAR_TEXT
                )
            },
            outputs={}  # 无输出
        )
    
    def handle(self, context, inputs, output_definitions):
        context = cast(HistoryLoggerContext, context)
        
        if inputs.type == ChatDataType.HUMAN_TEXT:
            text = inputs.data.get_main_data()
            context.log_file.write(f"[USER] {text}\n")
            context.log_file.flush()
        
        elif inputs.type == ChatDataType.AVATAR_TEXT:
            text = inputs.data.get_main_data()
            context.log_file.write(f"[AVATAR] {text}\n")
            context.log_file.flush()
        
        # 无输出
        return
        yield  # 使其成为生成器
    
    def destroy_context(self, context):
        context = cast(HistoryLoggerContext, context)
        if context.log_file:
            context.log_file.close()
```

---

## 最佳实践

### 1. 配置管理

✅ **使用Pydantic模型验证配置**
```python
class MyConfig(HandlerBaseConfigModel, BaseModel):
    param1: str = Field(..., description="必填参数")
    param2: int = Field(default=10, ge=1, le=100, description="范围1-100")
```

✅ **支持环境变量覆盖**
```python
api_key: str = Field(default=os.getenv("MY_API_KEY"))
```

### 2. 错误处理

✅ **优雅处理异常**
```python
def handle(self, context, inputs, output_definitions):
    try:
        result = self.model.process(data)
        yield create_output(result)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        # 返回错误标记或跳过
        return
```

### 3. 资源管理

✅ **及时释放资源**
```python
def destroy_context(self, context):
    if context.file_handle:
        context.file_handle.close()
    if context.buffer:
        context.buffer.clear()
```

### 4. 日志记录

✅ **记录关键信息**
```python
logger.info(f"Processing {len(data)} samples")
logger.debug(f"Model output: {result}")
logger.error(f"Failed to process: {e}")
```

### 5. 性能优化

✅ **批处理**
```python
# 累积数据批量处理
if len(context.buffer) >= batch_size:
    results = self.model.batch_process(context.buffer)
    context.buffer.clear()
```

✅ **异步处理**
```python
# 使用生成器流式输出
for chunk in self.model.stream_process(data):
    yield create_output(chunk)
```

### 6. 测试

✅ **单元测试**
```python
def test_handler():
    handler = MyHandler()
    handler.load(config)
    
    context = handler.create_context(session_context)
    result = list(handler.handle(context, test_input, output_defs))
    
    assert len(result) > 0
    assert result[0].type == ChatDataType.EXPECTED_TYPE
```

---

## 总结

### Handler的本质
Handler是OpenAvatarChat的**核心抽象**，它：
- 📦 **封装功能**: 每个Handler专注一个功能
- 🔌 **可插拔**: 通过配置文件灵活组合
- 🔄 **数据驱动**: 通过标准化数据类型通信
- 🎯 **职责单一**: 遵循单一职责原则

### Handler的价值
- ✅ **降低耦合**: Handler之间独立开发
- ✅ **提高复用**: 同一Handler可用于不同配置
- ✅ **易于扩展**: 添加新功能只需新增Handler
- ✅ **便于测试**: 每个Handler可独立测试

### 开发新Handler的步骤
1. 定义配置模型 (`Config`)
2. 定义上下文类 (`Context`)
3. 实现Handler类 (继承`HandlerBase`)
4. 实现7个核心方法
5. 创建依赖配置 (`pyproject.toml`)
6. 在配置文件中启用

---

**文档版本**: 1.0  
**更新日期**: 2026-02-12  
**作者**: OpenAvatarChat Team
