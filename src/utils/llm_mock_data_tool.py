import argparse
import json
import os
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from loguru import logger
from openai import OpenAI

# 允许直接以脚本方式运行：python src/utils/llm_mock_data_tool.py
CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from service.interview_db.sql_controller import InterviewSQLController
from utils.interview_db_config import load_interview_db_config


class InterviewMockDataTool:
    """使用 LLM 快速生成并入库面试模拟数据。"""

    def __init__(
        self,
        mysql_host: str,
        mysql_port: int,
        mysql_user: str,
        mysql_password: str,
        mysql_database: str,
        mysql_charset: str,
        api_key: str | None,
        api_url: str | None,
        model_name: str,
    ):
        self.controller = InterviewSQLController(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_database,
            charset=mysql_charset,
        )
        self.controller.init_tables()
        self.model_name = model_name
        self.client = None
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=api_url)

    def _build_prompt(self, count: int, checkpoint_per_interview: int) -> str:
        return (
            "请生成模拟面试数据，必须输出 JSON 对象且不能包含 markdown。"
            "JSON 结构：{\"records\": [...]}。"
            "每个 record 字段必须包含："
            "id, acatar_id, user_id, position_id, resume_id, source_config, process_config, "
            "status, started_at, completed_at, current_stage, stage_started_at, oss_base_path, report_id。"
            f"请生成 {count} 条 record。每条 record 额外包含 checkpoints 数组，"
            f"每条包含 {checkpoint_per_interview} 个 checkpoint。"
            "checkpoint 字段必须包含：checkpoint_id,current_stage,stage_progress,total_progress,realtime_scores,"
            "rag_context,begin_timestamp,end_timestamp,oss_path。"
            "时间字段格式统一为 YYYY-MM-DD HH:MM:SS。"
        )

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        text = text.strip()
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("LLM 输出不包含合法 JSON 对象")
        return json.loads(match.group(0))

    def _fallback_records(self, count: int, checkpoint_per_interview: int) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        now = datetime.utcnow()
        stages = ["greeting", "technical", "resume", "experience", "closing"]
        for i in range(count):
            interview_id = f"int_{uuid4().hex[:12]}"
            started_at = now - timedelta(minutes=30 + i * 3)
            completed_at = started_at + timedelta(minutes=20)
            checkpoints = []
            for idx in range(checkpoint_per_interview):
                stage_name = stages[min(idx, len(stages) - 1)]
                checkpoints.append(
                    {
                        "checkpoint_id": f"cp_{idx + 1:03d}",
                        "current_stage": stage_name,
                        "stage_progress": idx + 1,
                        "total_progress": idx + 1,
                        "realtime_scores": {
                            "clarity": round(random.uniform(3.0, 5.0), 2),
                            "accuracy": round(random.uniform(3.0, 5.0), 2),
                        },
                        "rag_context": {"enabled": bool(idx % 2), "ref": f"kb_chunk_{idx + 1}"},
                        "begin_timestamp": int((started_at + timedelta(minutes=idx * 2)).timestamp() * 1000),
                        "end_timestamp": int((started_at + timedelta(minutes=idx * 2 + 1)).timestamp() * 1000),
                        "oss_path": f"interviews/{interview_id}/checkpoints/cp_{idx + 1:03d}.json",
                    }
                )

            records.append(
                {
                    "id": interview_id,
                    "acatar_id": f"avatar_{uuid4().hex[:8]}",
                    "user_id": f"user_{1000 + i}",
                    "position_id": f"position_{200 + i}",
                    "resume_id": f"resume_{300 + i}",
                    "source_config": {
                        "position_id": f"position_{200 + i}",
                        "knowledge_base_ids": ["kb_java_backend", "kb_system_design"],
                        "question_bank_ids": ["qb_backend_mid"],
                        "resume_id": f"resume_{300 + i}",
                        "company_culture_id": "culture_default",
                    },
                    "process_config": {
                        "stages": [
                            {"type": "greeting", "duration": 3, "weight": 0.05, "order": 1},
                            {"type": "technical", "duration": 10, "weight": 0.55, "order": 2},
                            {"type": "resume", "duration": 8, "weight": 0.25, "order": 3},
                            {"type": "closing", "duration": 2, "weight": 0.15, "order": 4},
                        ],
                        "total_duration": 23,
                    },
                    "status": "completed",
                    "started_at": started_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "completed_at": completed_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "current_stage": "closing",
                    "stage_started_at": (completed_at - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    "oss_base_path": f"interviews/{interview_id}/",
                    "report_id": f"report_{uuid4().hex[:10]}",
                    "checkpoints": checkpoints,
                }
            )
        return records

    def generate_records(self, count: int, checkpoint_per_interview: int) -> List[Dict[str, Any]]:
        if self.client is None:
            logger.warning("未检测到 LLM API Key，使用本地兜底模拟数据。")
            return self._fallback_records(count, checkpoint_per_interview)

        try:
            completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是一个严谨的数据生成助手，只输出 JSON。"},
                    {"role": "user", "content": self._build_prompt(count, checkpoint_per_interview)},
                ],
                stream=False,
            )
            content = completion.choices[0].message.content if completion and completion.choices else ""
            payload = self._extract_json(content or "")
            records = payload.get("records")
            if not isinstance(records, list) or not records:
                raise ValueError("records 字段缺失或为空")
            return records
        except Exception as exc:
            logger.warning(f"LLM 生成失败，回退到本地模拟数据。error={exc}")
            return self._fallback_records(count, checkpoint_per_interview)

    def insert_records(self, records: List[Dict[str, Any]]):
        for record in records:
            checkpoints = record.pop("checkpoints", [])
            record.setdefault("created_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            record.setdefault("checkpoint_count", 0)
            record.setdefault("last_checkpoint_at", None)
            self.controller.create_interview_record(record)

            for checkpoint in checkpoints:
                checkpoint["interview_id"] = record["id"]
                checkpoint.setdefault("created_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
                self.controller.create_checkpoint(checkpoint)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM 模拟面试数据快速生成并入库工具")
    parser.add_argument("--config", default="config/chat_with_interview.yaml", help="主配置 YAML 路径")
    parser.add_argument("--env", default="default", help="Dynaconf 环境名")
    parser.add_argument("--mysql-host", default=None, help="MySQL 主机（可选覆盖配置）")
    parser.add_argument("--mysql-port", type=int, default=None, help="MySQL 端口（可选覆盖配置）")
    parser.add_argument("--mysql-user", default=None, help="MySQL 用户（可选覆盖配置）")
    parser.add_argument("--mysql-password", default=None, help="MySQL 密码（可选覆盖配置）")
    parser.add_argument("--mysql-database", default=None, help="MySQL 数据库名（可选覆盖配置）")
    parser.add_argument("--mysql-charset", default=None, help="MySQL 字符集（可选覆盖配置）")
    parser.add_argument("--count", type=int, default=5, help="生成的 interview 记录条数")
    parser.add_argument("--checkpoint-per-interview", type=int, default=4, help="每条记录生成的 checkpoint 数")
    parser.add_argument("--model-name", default="qwen-plus", help="用于生成模拟数据的模型名")
    parser.add_argument("--api-key", default=os.getenv("INTERVIEW_LLM_API_KEY", os.getenv("DASHSCOPE_API_KEY")))
    parser.add_argument("--api-url", default=os.getenv("INTERVIEW_LLM_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    return parser.parse_args()


def main():
    args = parse_args()
    db_cfg = load_interview_db_config(
        config_path=args.config,
        env=args.env,
        mysql_host=args.mysql_host,
        mysql_port=args.mysql_port,
        mysql_user=args.mysql_user,
        mysql_password=args.mysql_password,
        mysql_database=args.mysql_database,
        mysql_charset=args.mysql_charset,
    )

    tool = InterviewMockDataTool(
        mysql_host=db_cfg["host"],
        mysql_port=db_cfg["port"],
        mysql_user=db_cfg["user"],
        mysql_password=db_cfg["password"],
        mysql_database=db_cfg["database"],
        mysql_charset=db_cfg["charset"],
        api_key=args.api_key,
        api_url=args.api_url,
        model_name=args.model_name,
    )
    records = tool.generate_records(count=args.count, checkpoint_per_interview=args.checkpoint_per_interview)
    tool.insert_records(records)
    logger.info(
        "Mock data inserted successfully. mysql={}:{}@{}/{}, interview_count={}, checkpoint_per_interview={}, config={}, env={}",
        db_cfg["user"],
        "***" if db_cfg["password"] else "",
        db_cfg["host"],
        db_cfg["database"],
        len(records),
        args.checkpoint_per_interview,
        db_cfg["config_path"],
        db_cfg["env"],
    )


if __name__ == "__main__":
    main()
