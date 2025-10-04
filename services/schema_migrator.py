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
        ("groups", "id", False),
        ("users", "id", False),
        ("command_history", "user_id", True),
        ("command_history", "chat_id", True),
        ("command_history", "message_id", True),
        ("group_chat_history", "message_id", True),
        ("group_chat_history", "group_id", True),
        ("group_chat_history", "user_id", True),
        ("private_chat_history", "message_id", True),
        ("private_chat_history", "user_id", True),
        ("active_message_handler", "group_id", True),
        ("active_message_handler", "user_id", True),
    )

    for table_suffix, column, allow_autoincrement in targets:
        table_name = f"{prefix}{table_suffix}"
        await _ensure_column_bigint(
            conn,
            schema,
            table_name,
            column,
            allow_autoincrement=allow_autoincrement,
        )


async def _remove_auto_increment_flags(conn: AsyncConnection) -> None:
    schema = file_config.db_name
    prefix = file_config.db_prefix

    for table_suffix in ("groups", "users"):
        table_name = f"{prefix}{table_suffix}"
        await _ensure_column_bigint(
            conn,
            schema,
            table_name,
            "id",
            allow_autoincrement=False,
        )


async def _ensure_column_bigint(
    conn: AsyncConnection,
    schema: str,
    table_name: str,
    column: str,
    *,
    allow_autoincrement: bool,
) -> None:
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
        return

    data_type = (row["DATA_TYPE"] or "").lower()
    extra = (row["EXTRA"] or "").lower()

    needs_type_change = data_type != "bigint"
    needs_auto_increment_change = (
        not allow_autoincrement and "auto_increment" in extra
    )

    if not needs_type_change and not needs_auto_increment_change:
        return

    null_clause = "NULL" if row["IS_NULLABLE"] == "YES" else "NOT NULL"
    default_clause = _build_default_clause(row["COLUMN_DEFAULT"])
    comment_clause = _build_comment_clause(row["COLUMN_COMMENT"])

    extra_clause = ""
    if allow_autoincrement and extra:
        extra_clause = f" {extra.upper()}"

    sql = (
        f"ALTER TABLE {_quote(table_name)} "
        f"MODIFY COLUMN {_quote(column)} BIGINT "
        f"{null_clause}{default_clause}{comment_clause}{extra_clause}"
    )
    await conn.execute(text(sql))

    detail_message = []
    if needs_type_change:
        detail_message.append("type")
    if needs_auto_increment_change:
        detail_message.append("AUTO_INCREMENT flag")

    logger.info(
        "Adjusted %s.%s (%s)",
        table_name,
        column,
        " and ".join(detail_message),
    )


def _build_default_clause(default_value) -> str:
    if default_value is None:
        return ""

    if isinstance(default_value, bytes):
        default_value = default_value.decode()

    if isinstance(default_value, str):
        if default_value.upper() == "NULL":
            return " DEFAULT NULL"
        escaped = default_value.replace("'", "''")
        return f" DEFAULT '{escaped}'"

    return f" DEFAULT {default_value}"


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
    Migration(
        version=2,
        name="Remove AUTO_INCREMENT from Telegram ID columns",
        handler=_remove_auto_increment_flags,
    ),
)
