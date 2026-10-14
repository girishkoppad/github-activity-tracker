"""Test setup. Tests run against a SEPARATE database (<your db>_test), never your real data.

The test database is created automatically if it does not exist.
"""
import asyncio
import os

import asyncpg
import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url


def _point_at_test_database() -> None:
    """Swap DATABASE_URL for the test database BEFORE the app modules are imported."""
    raw = os.getenv("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is not set. Create your .env file first.")
    url = make_url(raw)
    test_name = f"{url.database}_test"

    async def ensure_exists() -> None:
        conn = await asyncpg.connect(
            user=url.username,
            password=url.password,
            host=url.host,
            port=url.port,
            database="postgres",  # the built-in maintenance database
        )
        try:
            found = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", test_name)
            if not found:
                await conn.execute(f'CREATE DATABASE "{test_name}"')
        finally:
            await conn.close()

    asyncio.run(ensure_exists())
    os.environ["DATABASE_URL"] = url.set(database=test_name).render_as_string(hide_password=False)


_point_at_test_database()

# Imported only now, so they pick up the test DATABASE_URL.
import models  # noqa: E402,F401
from database import Base, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def create_schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def empty_tables():
    """Every test starts with empty tables."""
    async with engine.begin() as conn:
        await conn.exec_driver_sql("TRUNCATE organizations RESTART IDENTITY CASCADE")
    yield