"""开发库先完整备份并验证恢复，再按当前 ORM 重建空库；不转换或回填旧结果"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from src.storage.database_url import resolve_database_url_from_env


def inventory(connection):
    """对全部业务表核对行数和内容摘要，不只检查原文表"""
    tables = list(
        connection.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema') "
                "ORDER BY table_schema, table_name"
            )
        ).mappings()
    )
    counts, digests = {}, {}
    for row in tables:
        qualified = ".".join(
            connection.dialect.identifier_preparer.quote(row[key]) for key in ("table_schema", "table_name")
        )
        key = f"{row['table_schema']}.{row['table_name']}"
        counts[key] = connection.execute(text(f"SELECT count(*) FROM {qualified}")).scalar_one()
        digest = hashlib.sha256()
        for value in connection.execute(
            text(
                f"SELECT row_to_json(record)::text AS value FROM {qualified} record ORDER BY row_to_json(record)::text"
            )
        ).mappings():
            digest.update(value["value"].encode("utf-8"))
            digest.update(b"\n")
        digests[key] = digest.hexdigest()
    return {"counts": counts, "digests": digests}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def database_properties(connection, name):
    result = dict(
        connection.execute(
            text(
                "SELECT pg_get_userbyid(datdba) AS owner,pg_encoding_to_char(encoding) AS encoding,"
                "datcollate,datctype,datlocprovider,datacl,datconnlimit,t.spcname AS tablespace "
                "FROM pg_database d JOIN pg_tablespace t ON t.oid=d.dattablespace WHERE datname=:name"
            ),
            {"name": name},
        )
        .mappings()
        .one()
    )
    result["settings"] = [
        dict(row)
        for row in connection.execute(
            text(
                "SELECT setrole::text,setconfig FROM pg_db_role_setting "
                "WHERE setdatabase=(SELECT oid FROM pg_database WHERE datname=:name)"
            ),
            {"name": name},
        ).mappings()
    ]
    return result


def create_database(connection, name, properties):
    # 当前开发库为默认权限/配置；非默认库停止，而不是悄悄丢失数据库级属性
    if properties["datacl"] is not None or properties["settings"] or properties["datlocprovider"] != "c":
        raise RuntimeError("数据库有非默认权限、配置或locale provider，本入口不支持清空")
    quote = connection.dialect.identifier_preparer.quote
    connection.execute(
        text(
            f"CREATE DATABASE {quote(name)} WITH TEMPLATE template0 OWNER {quote(properties['owner'])} "
            f"ENCODING {literal(properties['encoding'])} LC_COLLATE {literal(properties['datcollate'])} "
            f"LC_CTYPE {literal(properties['datctype'])} TABLESPACE {quote(properties['tablespace'])} "
            f"CONNECTION LIMIT {int(properties['datconnlimit'])}"
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--backup-directory", type=Path, required=True)
    parser.add_argument("--rebuild", action="store_true", help="备份恢复验证通过后清空重建指定开发库")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    url = make_url(resolve_database_url_from_env("DATABASE"))
    name = url.database
    if (
        name != args.expected_database
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or "")
        or name in {"postgres", "template0", "template1"}
    ):
        raise SystemExit("实际目标数据库与显式预期不一致或属于系统库，停止")
    if os.environ.get("DATABASE_SCHEMA"):
        raise SystemExit("配置了DATABASE_SCHEMA，不能执行整库重建")
    dump = shutil.which("pg_dump")
    restore = shutil.which("pg_restore")
    if not dump or not restore:
        raise SystemExit("缺少PostgreSQL pg_dump/pg_restore")
    backup_dir = args.backup_directory.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"{name}-{stamp}-{uuid4().hex[:8]}.dump"
    connection_args = [
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username or "postgres",
    ]
    task_env = dict(os.environ)
    task_env["PGPASSWORD"] = url.password or ""
    source = create_engine(url, poolclass=NullPool)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    verify_name = f"{name}_verify_{uuid4().hex[:12]}"
    manifest = backup.with_suffix(".json")
    receipt = {
        "database": name,
        "backup": str(backup),
        "restoration_verified": False,
        "rebuild_completed": False,
        "stage": "preparing",
    }

    def checkpoint(stage):
        receipt["stage"] = stage
        manifest.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")

    protected = False
    pinned = None
    try:
        with admin.connect() as connection:
            properties = database_properties(connection, name)
            if properties["datacl"] is not None or properties["settings"] or properties["datlocprovider"] != "c":
                raise RuntimeError("源库使用非默认数据库级配置/权限，停止清空")
            receipt["database_properties"] = properties
            # 终止旧事务后，用全部业务表的事务锁阻止写入；不将维护配置写入备份
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:name AND pid<>pg_backend_pid()"
                ),
                {"name": name},
            )
        pinned = source.connect()
        pinned.execute(text("SET LOCAL lock_timeout='30s'"))
        tables = list(
            pinned.execute(
                text(
                    "SELECT schemaname,tablename FROM pg_tables "
                    "WHERE schemaname NOT IN ('pg_catalog','information_schema')"
                )
            ).mappings()
        )
        if tables:
            quote = pinned.dialect.identifier_preparer.quote
            qualified = ",".join(f"{quote(row['schemaname'])}.{quote(row['tablename'])}" for row in tables)
            pinned.execute(text(f"LOCK TABLE {qualified} IN SHARE MODE"))
        # SHARE锁保持到禁止连接并终止其他会话之后；pg_dump使用同一导出快照
        locked_tables = {f"{row['schemaname']}.{row['tablename']}" for row in tables}
        before = inventory(pinned)
        if set(before["counts"]) != locked_tables:
            raise RuntimeError("获取表锁期间表目录变化，停止备份和清空")
        receipt["inventory"] = before
        snapshot = pinned.execute(text("SELECT pg_export_snapshot()")).scalar_one()
        checkpoint("backup_started")
        print(f"持续停写保护已建立，开始完整备份：{name} → {backup}", flush=True)
        subprocess.run(
            [
                dump,
                *connection_args,
                "--dbname",
                name,
                "--format=custom",
                "--lock-wait-timeout=30s",
                "--snapshot",
                snapshot,
                "--file",
                str(backup),
            ],
            env=task_env,
            check=True,
        )
        if inventory(pinned) != before:
            raise RuntimeError("源库目录或内容变化，停止重建")
        with admin.connect() as connection:
            create_database(connection, verify_name, properties)
        checkpoint("restore_verification_started")
        print(f"正在临时库恢复验证：{verify_name}", flush=True)
        subprocess.run(
            [restore, *connection_args, "--dbname", verify_name, "--exit-on-error", str(backup)],
            env=task_env,
            check=True,
        )
        verify = create_engine(url.set(database=verify_name), poolclass=NullPool)
        try:
            with verify.connect() as connection:
                if inventory(connection) != before:
                    raise RuntimeError("完整备份恢复内容核对失败，禁止清空源库")
            with admin.connect() as connection:
                if database_properties(connection, verify_name) != properties:
                    raise RuntimeError("恢复库数据库级属性不同，禁止清空源库")
        finally:
            verify.dispose()
        receipt.update(
            sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
            bytes=backup.stat().st_size,
            restoration_verified=True,
        )
        checkpoint("restore_verified")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{verify_name}"'))
        print(f"恢复核对通过：{len(before['counts'])} 张表全部内容，SHA256={receipt['sha256']}", flush=True)
        if args.rebuild:
            with admin.connect() as connection:
                connection.execute(text(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS=false'))
                protected = True
                keeper = pinned.execute(text("SELECT pg_backend_pid()")).scalar_one()
                connection.execute(
                    text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name AND pid<>:keeper"),
                    {"name": name, "keeper": keeper},
                )
            if inventory(pinned) != before:
                raise RuntimeError("最终目录或内容核对失败，禁止清空源库")
            checkpoint("drop_started")
            pinned.rollback()
            pinned.close()
            pinned = None
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))
                checkpoint("source_dropped")
                create_database(connection, name, properties)
            protected = False
            checkpoint("empty_database_created")
            from src.storage.db import dispose_engine, init_db

            dispose_engine()
            init_db()
            with source.connect() as connection:
                rebuilt = inventory(connection)
            if any(rebuilt["counts"].values()):
                raise RuntimeError("新库不为空，停止")
            with admin.connect() as connection:
                if database_properties(connection, name) != properties:
                    raise RuntimeError("新库数据库级属性核对失败")
            receipt.update(rebuild_completed=True, rebuilt_tables=list(rebuilt["counts"]))
            checkpoint("rebuild_verified")
            print(f"开发库已重建为空库：{name}，{len(rebuilt['counts'])} 张表；旧库完整保存在备份", flush=True)
    except BaseException:
        receipt["failed_stage"] = receipt["stage"]
        checkpoint("failed")
        print(f"操作失败，依据核对记录确认当前阶段：{manifest}；已生成的备份与验证库保留", flush=True)
        raise
    finally:
        if pinned is not None:
            pinned.rollback()
            pinned.close()
        if protected:
            with admin.connect() as connection:
                if connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
                ).scalar_one_or_none():
                    connection.execute(text(f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS=true'))
        source.dispose()
        admin.dispose()
    print(f"核对记录：{manifest}", flush=True)


if __name__ == "__main__":
    main()
