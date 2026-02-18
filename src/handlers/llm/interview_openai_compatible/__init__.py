"""模拟面试场景的 OpenAI 兼容 LLM Handler 包。"""

# 对外导出统一入口，便于按模块路径动态加载。
from .llm_handler_interview_openai_compatible import HandlerInterviewLLM

__all__ = ["HandlerInterviewLLM"]
