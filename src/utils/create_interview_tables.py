import argparse
import sys
from pathlib import Path

import pymysql
from loguru import logger

# 允许直接以脚本方式运行：python src/utils/create_interview_tables.py
CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from service.interview_db.sql_controller import InterviewSQLController
from utils.interview_db_config import load_interview_db_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="根据完善后的 MySQL SQL 创建 interview 数据表")
    parser.add_argument("--config", default="config/chat_with_interview.yaml", help="主配置 YAML 路径")
    parser.add_argument("--env", default="default", help="Dynaconf 环境名")
    parser.add_argument("--mysql-host", default=None, help="MySQL 主机（可选覆盖配置）")
    parser.add_argument("--mysql-port", type=int, default=None, help="MySQL 端口（可选覆盖配置）")
    parser.add_argument("--mysql-user", default=None, help="MySQL 用户（可选覆盖配置）")
    parser.add_argument("--mysql-password", default=None, help="MySQL 密码（可选覆盖配置）")
    parser.add_argument("--mysql-database", default=None, help="MySQL 数据库名（可选覆盖配置）")
    parser.add_argument("--mysql-charset", default=None, help="MySQL 字符集（可选覆盖配置）")
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
    sql_list = InterviewSQLController.get_schema_sql_list()

    conn = pymysql.connect(
        host=db_cfg["host"],
        port=db_cfg["port"],
        user=db_cfg["user"],
        password=db_cfg["password"],
        database=db_cfg["database"],
        charset=db_cfg["charset"],
        autocommit=False,
    )
    try:
        with conn.cursor() as cursor:
            for statement in sql_list:
                cursor.execute(statement)
        conn.commit()
        logger.info(
            "Interview tables created successfully. mysql_user={}, mysql_host={}, mysql_database={}, sql_count={}, config={}, env={}",
            db_cfg["user"],
            db_cfg["host"],
            db_cfg["database"],
            len(sql_list),
            db_cfg["config_path"],
            db_cfg["env"],
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
