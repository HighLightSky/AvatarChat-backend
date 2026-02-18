# 模拟面试 LLM Handler（MVP）设计与实现说明

## 1. 目标

在保持 `openai_compatible` 处理方式一致的前提下，实现一个面向“模拟面试会话”的 LLM Handler：

- 输入/输出协议保持一致：
  - 输入：`HUMAN_TEXT`（可选 `CAMERA_VIDEO`）
  - 触发：`human_text_end=True` 触发一轮推理
  - 输出：流式 `AVATAR_TEXT` + 结束标记 `avatar_text_end=True`
- 支持**固定轮数驱动的阶段切换**（简化顺序流转）
- checkpoint 仅本地构建 payload（不接业务后端）
- RAG / 实时评估保留接口，先用 Null Object 空实现

---

## 2. 新增模块

目录：`src/handlers/llm/interview_openai_compatible/`

1. `llm_handler_interview_openai_compatible.py`
   - `InterviewLLMConfig`
   - `InterviewLLMContext`
   - `HandlerInterviewLLM`
2. `interview_history_manager.py`
   - `InterviewHistoryManager`
   - `HistoryMessage`
3. `interview_flow_controller.py`
   - `InterviewFlowController`
4. `interview_state_models.py`
   - `InterviewStageType`
   - `StageDefinition`
   - `StageRuntimeState`
   - `TurnResult`
   - `CheckpointPayload`
5. `ports.py`
   - `RagPort` / `EvaluationPort` 抽象接口
   - `NullRagPort` / `NullEvaluationPort` 空实现
6. `__init__.py`
   - 对外导出 `HandlerInterviewLLM`

---

## 3. MVP 流程

1. 接收输入：
   - 视频输入仅更新当前帧
   - 文本输入累积到本轮缓存
2. 未收到 `human_text_end`：继续等待
3. 收到 `human_text_end=True`：触发本轮 LLM
4. 拼装 messages：
   - 系统提示词 + 历史 + 当前用户输入
   - 注入当前阶段提示（stage hint）
5. 流式输出文本片段
6. 本轮完成后：
   - 写入历史
   - 推进阶段轮数，必要时切换到下一阶段
   - 本地构建 checkpoint payload
   - 输出 `avatar_text_end=True`

---

## 4. 固定轮数阶段切换（MVP）

默认阶段顺序：

1. `greeting`
2. `technical`
3. `resume`
4. `experience`
5. `closing`

每个阶段配置固定轮次上限（可在配置中覆盖）。
当某阶段达到上限后自动切换到下一阶段。

---

## 5. 空实现建议（简短）

### 5.1 NullRagPort
- 现状：返回空检索结果，不改变主流程。
- 建议实现：在 `retrieve()` 中接入向量检索服务，返回“片段 + 置信度 + 来源”。

### 5.2 NullEvaluationPort
- 现状：返回占位评分，不影响回复。
- 建议实现：在 `evaluate_turn()` 中按阶段输出维度化评分（表达、准确性、深度等），写入 checkpoint。

---

## 6. 配置建议（MVP）

- `model_name`, `api_key`, `api_url`
- `system_prompt`
- `history_length`
- `enable_video_input`
- `stage_order`
- `stage_turn_limits`
- `checkpoint_enabled`

---

## 7. 后续演进方向

1. 用“语义完成度 + 时间预算”替代固定轮数切换
2. 将 checkpoint 异步同步到业务后端
3. 加入阶段专属提问策略
4. 引入面试中断/恢复（checkpoint restore）
