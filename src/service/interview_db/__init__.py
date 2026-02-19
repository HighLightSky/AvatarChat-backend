"""面试数据库模块。

提供独立的 SQL 控制器入口，专门负责 interview 相关表的 CRUD。
"""

from .sql_controller import InterviewSQLController

__all__ = ["InterviewSQLController"]
