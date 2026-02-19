import json
import pymysql
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


class InterviewSQLController:
    """面试数据库 SQL 控制器（独立模块）。

    说明：
    1) 该模块只负责 interview_records / interview_checkpoints 两张表的 CRUD；
    2) 使用 MySQL（pymysql）执行 SQL；
    3) 字段名与文档保持一致，JSON 字段以字符串形式存储。
    """

    def __init__(self, host: str, port: int, user: str, password: str, database: str, charset: str = "utf8mb4"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.charset = charset

    @contextmanager
    def _connection(self):
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset=self.charset,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _to_json_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _schema_sql() -> Iterable[str]:
        """返回 interview 相关表的建表 SQL（MySQL）。"""
        return [
            """
            CREATE TABLE IF NOT EXISTS interview_records (
                id VARCHAR(32) PRIMARY KEY COMMENT '面试ID',
                acatar_id VARCHAR(50) COMMENT '数字人会话实例ID',
                user_id VARCHAR(32) NOT NULL COMMENT '用户ID',
                position_id VARCHAR(32) COMMENT '岗位ID',
                resume_id VARCHAR(32) COMMENT '简历ID',
                source_config JSON COMMENT '源数据配置：{position_id, knowledge_base_ids[], question_bank_ids[], resume_id, company_culture_id}',
                process_config JSON COMMENT '流程配置：{stages: [{type, duration, weight, order}], total_duration}',
                status ENUM(
                    'draft',
                    'initializing',
                    'ready',
                    'in_progress',
                    'paused',
                    'completed',
                    'terminated',
                    'processing',
                    'archived'
                ) DEFAULT 'draft' NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                started_at DATETIME COMMENT '面试开始时间',
                completed_at DATETIME COMMENT '面试完成时间',
                archived_at DATETIME COMMENT '归档时间',
                current_stage VARCHAR(50) COMMENT '当前阶段',
                stage_started_at DATETIME COMMENT '当前阶段开始时间',
                oss_base_path VARCHAR(500) COMMENT 'OSS基础路径: interviews/{interview_id}/',
                checkpoint_count INT DEFAULT 0 COMMENT '检查点数量',
                last_checkpoint_at DATETIME COMMENT '最后检查点时间',
                report_id VARCHAR(32) COMMENT '评估报告ID（可关联评估报告表）',
                KEY idx_user_id (user_id),
                KEY idx_status (status),
                KEY idx_current_stage (current_stage),
                KEY idx_created_at (created_at),
                KEY idx_report_id (report_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='面试记录表'
            """,
            """
            CREATE TABLE IF NOT EXISTS interview_checkpoints (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                interview_id VARCHAR(32) NOT NULL COMMENT '面试ID',
                checkpoint_id VARCHAR(32) NOT NULL COMMENT '检查点序号',
                current_stage VARCHAR(50) NOT NULL COMMENT '当前阶段',
                stage_progress INT NOT NULL COMMENT '阶段进度',
                total_progress INT NOT NULL COMMENT '总进度',
                realtime_scores JSON COMMENT '本轮对话评分',
                rag_context JSON COMMENT 'RAG检索上下文（如果本轮对话调用RAG）',
                begin_timestamp BIGINT COMMENT '开始时间戳',
                end_timestamp BIGINT COMMENT '结束时间戳',
                oss_path VARCHAR(500) COMMENT '检查点OSS存储路径',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_interview_checkpoint (interview_id, checkpoint_id),
                KEY idx_current_stage (current_stage),
                KEY idx_created_at (created_at),
                CONSTRAINT fk_checkpoint_interview
                    FOREIGN KEY (interview_id) REFERENCES interview_records(id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='面试检查点表'
            """,
        ]

    @classmethod
    def get_schema_sql_list(cls) -> List[str]:
        """对外暴露建表 SQL 列表，供独立 utils 直接执行。"""
        return list(cls._schema_sql())

    def init_tables(self):
        """初始化数据表（MySQL 版本）。"""
        with self._connection() as conn:
            with conn.cursor() as cursor:
                for statement in self._schema_sql():
                    cursor.execute(statement)

    def create_interview_record(self, record: Dict[str, Any]):
        fields = [
            "id", "acatar_id", "user_id", "position_id", "resume_id",
            "source_config", "process_config", "status", "created_at",
            "started_at", "completed_at", "archived_at", "current_stage",
            "stage_started_at", "oss_base_path", "checkpoint_count",
            "last_checkpoint_at", "report_id",
        ]
        payload = {k: record.get(k) for k in fields}
        payload["source_config"] = self._to_json_text(payload["source_config"])
        payload["process_config"] = self._to_json_text(payload["process_config"])
        if not payload.get("created_at"):
            payload["created_at"] = self._now()

        placeholders = ",".join(["%s"] * len(fields))
        sql = f"INSERT INTO interview_records ({','.join(fields)}) VALUES ({placeholders})"
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, [payload[field] for field in fields])

    def get_interview_record(self, interview_id: str) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM interview_records WHERE id = %s", (interview_id,))
                return cursor.fetchone()

    def list_interview_records(self, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM interview_records ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
                return list(cursor.fetchall())

    def update_interview_record(self, interview_id: str, updates: Dict[str, Any]) -> int:
        if not updates:
            return 0
        payload = dict(updates)
        if "source_config" in payload:
            payload["source_config"] = self._to_json_text(payload["source_config"])
        if "process_config" in payload:
            payload["process_config"] = self._to_json_text(payload["process_config"])

        assignments = ", ".join([f"{key} = %s" for key in payload.keys()])
        sql = f"UPDATE interview_records SET {assignments} WHERE id = %s"
        values = list(payload.values()) + [interview_id]
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, values)
                return cursor.rowcount

    def delete_interview_record(self, interview_id: str) -> int:
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM interview_records WHERE id = %s", (interview_id,))
                return cursor.rowcount

    def create_checkpoint(self, checkpoint: Dict[str, Any]):
        fields = [
            "interview_id", "checkpoint_id", "current_stage", "stage_progress",
            "total_progress", "realtime_scores", "rag_context", "begin_timestamp",
            "end_timestamp", "oss_path", "created_at",
        ]
        payload = {k: checkpoint.get(k) for k in fields}
        payload["realtime_scores"] = self._to_json_text(payload["realtime_scores"])
        payload["rag_context"] = self._to_json_text(payload["rag_context"])
        if not payload.get("created_at"):
            payload["created_at"] = self._now()

        placeholders = ",".join(["%s"] * len(fields))
        sql = f"INSERT INTO interview_checkpoints ({','.join(fields)}) VALUES ({placeholders})"
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, [payload[field] for field in fields])
                cursor.execute(
                    """
                    UPDATE interview_records
                    SET checkpoint_count = checkpoint_count + 1,
                        last_checkpoint_at = %s
                    WHERE id = %s
                    """,
                    (payload["created_at"], payload["interview_id"]),
                )

    def list_checkpoints(self, interview_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM interview_checkpoints
                    WHERE interview_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (interview_id, limit),
                )
                return list(cursor.fetchall())

    def update_checkpoint(self, interview_id: str, checkpoint_id: str, updates: Dict[str, Any]) -> int:
        if not updates:
            return 0
        payload = dict(updates)
        if "realtime_scores" in payload:
            payload["realtime_scores"] = self._to_json_text(payload["realtime_scores"])
        if "rag_context" in payload:
            payload["rag_context"] = self._to_json_text(payload["rag_context"])

        assignments = ", ".join([f"{key} = %s" for key in payload.keys()])
        sql = f"UPDATE interview_checkpoints SET {assignments} WHERE interview_id = %s AND checkpoint_id = %s"
        values = list(payload.values()) + [interview_id, checkpoint_id]
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, values)
                return cursor.rowcount

    def delete_checkpoint(self, interview_id: str, checkpoint_id: str) -> int:
        with self._connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM interview_checkpoints WHERE interview_id = %s AND checkpoint_id = %s",
                    (interview_id, checkpoint_id),
                )
                return cursor.rowcount
