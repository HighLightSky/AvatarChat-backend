import os
from pathlib import Path
from typing import Any, Dict, Optional

from dynaconf import Dynaconf

from engine_utils.directory_info import DirectoryInfo


def _pick_first(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_project_config_path(config_path: str) -> str:
    if os.path.isabs(config_path):
        return config_path
    return str(Path(DirectoryInfo.get_project_dir()) / config_path)


def load_interview_db_config(
    config_path: str = "config/chat_with_interview.yaml",
    env: str = "default",
    mysql_host: Optional[str] = None,
    mysql_port: Optional[int] = None,
    mysql_user: Optional[str] = None,
    mysql_password: Optional[str] = None,
    mysql_database: Optional[str] = None,
    mysql_charset: Optional[str] = None,
) -> Dict[str, Any]:
    """加载 interview MySQL 配置。

    优先级：CLI 显式传参 > 主 YAML(mysql段) > .env 环境变量 > 硬编码默认值
    """

    os.environ["ENV_FOR_DYNACONF"] = env
    full_config_path = resolve_project_config_path(config_path)

    settings = Dynaconf(
        settings_files=[full_config_path],
        environments=True,
        load_dotenv=True,
    )

    chat_engine_cfg = settings.get("chat_engine", {}) or {}
    handler_cfg = chat_engine_cfg.get("handler_configs", {}) or {}
    interview_cfg = handler_cfg.get("LLMInterviewOpenAICompatible", {}) or {}
    mysql_cfg = interview_cfg.get("mysql", {}) or {}

    host = _pick_first(
        mysql_host,
        mysql_cfg.get("host"),
        os.getenv("INTERVIEW_DB_HOST"),
        "127.0.0.1",
    )
    port = _to_int(
        _pick_first(
            mysql_port,
            mysql_cfg.get("port"),
            os.getenv("INTERVIEW_DB_PORT"),
            3306,
        ),
        3306,
    )
    user = _pick_first(
        mysql_user,
        mysql_cfg.get("user"),
        os.getenv("INTERVIEW_DB_USER"),
        "root",
    )
    password = _pick_first(
        mysql_password,
        mysql_cfg.get("password"),
        os.getenv("INTERVIEW_DB_PASSWORD"),
        "",
    )
    database = _pick_first(
        mysql_database,
        mysql_cfg.get("database"),
        os.getenv("INTERVIEW_DB_NAME"),
        "open_avatar_chat",
    )
    charset = _pick_first(
        mysql_charset,
        mysql_cfg.get("charset"),
        os.getenv("INTERVIEW_DB_CHARSET"),
        "utf8mb4",
    )

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
        "charset": charset,
        "config_path": full_config_path,
        "env": env,
    }
