"""Integration fixtures: every test module gets its own Postgres schema, dropped afterwards.

Needs a reachable Postgres with pgvector (`make up`). The URL comes from TEST_DATABASE_URL
or, by default, DATABASE_URL. If the database is not reachable the tests are skipped.
"""

import os
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg_pool import AsyncConnectionPool

from bank_assistant.config import get_settings
from bank_assistant.db import apply_schema, open_pool


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", get_settings().database_url)
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA public")
            conn.commit()
    except psycopg.OperationalError as error:
        pytest.skip(f"Postgres not reachable ({error.__class__.__name__}); run `make up`")
    return url


@pytest.fixture(scope="module")
async def schema_conninfo(database_url: str) -> AsyncIterator[str]:
    schema = f"test_{uuid.uuid4().hex[:10]}"
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as admin:
        await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conninfo = make_conninfo(database_url, options=f"-c search_path={schema},public")
        async with await psycopg.AsyncConnection.connect(conninfo) as conn:
            await apply_schema(conn)
        yield conninfo
        await admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture(scope="module")
async def pool(schema_conninfo: str) -> AsyncIterator[AsyncConnectionPool]:
    pool = await open_pool(schema_conninfo)
    yield pool
    await pool.close()
