import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")

# The engine owns the connection pool (a set of reusable open connections).
engine = create_async_engine(DATABASE_URL, echo=False)

# A factory that creates a fresh AsyncSession (one conversation with the database).
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency: give each request its own session, close it afterwards."""
    async with SessionLocal() as session:
        yield session