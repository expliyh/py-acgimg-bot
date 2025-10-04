import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from configs import config as file_config


logger = logging.getLogger(__name__)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _quote(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Invalid identifier: {identifier!r}")
    return f"`{identifier}`"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    handler: Callable[[AsyncConnection], Awaitable[None]]


async def ensure_schema_migrations(async_engine: AsyncEngine) -> None:
    if async_engine is None:
        raise ValueError("Async engine is not initialized")

    table_name = f"{file_config.db_prefix}schema_migrations"
    async with async_engine.begin() as conn:
        await _ensure_version_table(conn, table_name)
        current_version = await _get_current_version(conn, table_name)

        for migration in sorted(_MIGRATIONS, key=lambda m: m.version):
            if migration.version <= current_version:
                continue

            logger.info(
                "Applying database migration %s: %s",
                migration.version,
                migration.name,
            )
            await migration.handler(conn)
            await _record_migration(conn, table_name, migration.version)
            current_version = migration.version


async def _ensure_version_table(conn: AsyncConnection, table_name: str) -> None:
    quoted_table = _quote(table_name)
    await conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {quoted_table} (
                version INT NOT NULL PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB
            """
        )
    )


async def _get_current_version(conn: AsyncConnection, table_name: str) -> int:
    result = await conn.execute(
        text(f"SELECT MAX(version) FROM {_quote(table_name)}")
    )
    value = result.scalar()
    return int(value or 0)


async def _record_migration(
    conn: AsyncConnection, table_name: str, version: int
) -> None:
    await conn.execute(
        text(
            f"""
            INSERT INTO {_quote(table_name)} (version)
            VALUES (:version)
            ON DUPLICATE KEY UPDATE applied_at = CURRENT_TIMESTAMP
            """
        ),
        {"version": version},
    )


async def _expand_telegram_ids(conn: AsyncConnection) -> None:
    schema = file_config.db_name
    prefix = file_config.db_prefix

    targets = (
        ("groups", "id"),
        ("users", "id"),
        ("command_history", "user_id"),
        ("command_history", "chat_id"),
        ("command_history", "message_id"),
        ("group_chat_history", "message_id"),
        ("group_chat_history", "group_id"),
        ("group_chat_history", "user_id"),
        ("private_chat_history", "message_id"),
        ("private_chat_history", "user_id"),
        ("active_message_handler", "group_id"),
        ("active_message_handler", "user_id"),
    )

    for table_suffix, column in targets:
        table_name = f"{prefix}{table_suffix}"
        column_info = await conn.execute(
            text(
                """
                SELECT DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT, EXTRA
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = :schema
                  AND TABLE_NAME = :table
                  AND COLUMN_NAME = :column
                """
            ),
            {"schema": schema, "table": table_name, "column": column},
        )
        row = column_info.mappings().first()
        if row is None:
            logger.debug(
                "Column %s.%s not found while migrating; skipping",
                table_name,
                column,
            )
            continue

        data_type = (row["DATA_TYPE"] or "").lower()
        if data_type == "bigint":
            continue

        null_clause = "NULL" if row["IS_NULLABLE"] == "YES" else "NOT NULL"
        default_clause = _build_default_clause(row["COLUMN_DEFAULT"])
        comment_clause = _build_comment_clause(row["COLUMN_COMMENT"])
        extra_clause = f" {row['EXTRA'].upper()}" if row["EXTRA"] else ""

        sql = (
            f"ALTER TABLE {_quote(table_name)} "
            f"MODIFY COLUMN {_quote(column)} BIGINT "
            f"{null_clause}{default_clause}{comment_clause}{extra_clause}"
        )
        await conn.execute(text(sql))
        logger.info("Converted %s.%s to BIGINT", table_name, column)


def _build_default_clause(default_value: str | None) -> str:
    if default_value is None:
        return ""
    if default_value.upper() == "NULL":
        return " DEFAULT NULL"
    return f" DEFAULT '{default_value.replace("'", "''")}'"


def _build_comment_clause(comment: str | None) -> str:
    if not comment:
        return ""
    return f" COMMENT '{comment.replace("'", "''")}'"


_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="Expand Telegram ID columns to BIGINT",
        handler=_expand_telegram_ids,
    ),
)
