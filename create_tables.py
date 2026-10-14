import asyncio

from database import Base, engine
import models  # noqa: F401  (importing registers the tables on Base)


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Tables created.")


if __name__ == "__main__":
    asyncio.run(main())