"""Postgres access: connection pool, schema bootstrap and vector literals."""

from collections.abc import Sequence
from importlib.resources import files

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


def schema_sql() -> str:
    return files("bank_assistant").joinpath("sql/schema.sql").read_text(encoding="utf-8")


async def apply_schema(conn: AsyncConnection) -> None:
    async with conn.transaction():
        await conn.execute(schema_sql())  # trusted static file shipped with the package


async def open_pool(conninfo: str, *, min_size: int = 1, max_size: int = 5) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(conninfo, min_size=min_size, max_size=max_size, open=False)
    await pool.open(wait=True, timeout=10)
    return pool


def vector_literal(values: Sequence[float]) -> str:
    """pgvector text format ('[0.1,0.2,...]'); passed as a parameter and cast with ::vector.

    Avoids depending on a client-side adapter: the cast is explicit in the SQL.
    """
    return "[" + ",".join(f"{value:.7g}" for value in values) + "]"
