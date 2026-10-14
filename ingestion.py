import asyncio
import os
import sys

import aiohttp
from dotenv import load_dotenv
from sqlalchemy import select

from database import SessionLocal, engine
from models import Organization, RepoSnapshot

load_dotenv()

API_BASE = os.getenv("GITHUB_API_BASE", "https://api.github.com")
TOKEN = os.getenv("GITHUB_TOKEN")  # optional but strongly recommended (60 vs 5000 req/hour)
DEFAULT_ORGS = ["vercel", "supabase", "fastapi"]


def build_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "github-tracker"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


async def fetch_repos(http: aiohttp.ClientSession, org: str) -> tuple[str, list[dict]]:
    """Fetch up to 100 repos of one organization. Returns (org, repos). Never raises."""
    url = f"{API_BASE}/orgs/{org}/repos?per_page=100"
    try:
        async with http.get(url) as resp:
            if resp.status != 200:
                print(f"[WARN] {org}: HTTP {resp.status}")
                return org, []
            return org, await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        print(f"[WARN] {org}: request failed ({exc})")
        return org, []


async def save_org(org: str, repos: list[dict]) -> int:
    """Save one organization's repos using its OWN session (safe for concurrent use)."""
    if not repos:
        return 0
    async with SessionLocal() as session:
        result = await session.execute(select(Organization).where(Organization.login == org))
        organization = result.scalar_one_or_none()
        if organization is None:
            organization = Organization(login=org)
            session.add(organization)
            await session.flush()  # sends the INSERT so organization.id exists

        for r in repos:
            session.add(
                RepoSnapshot(
                    organization_id=organization.id,
                    repo_name=r["name"],
                    language=r.get("language"),
                    stars=r.get("stargazers_count", 0),
                    forks=r.get("forks_count", 0),
                    open_issues=r.get("open_issues_count", 0),
                )
            )
        await session.commit()
    return len(repos)


async def run(orgs: list[str]) -> None:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(headers=build_headers(), timeout=timeout) as http:
        # All organizations are fetched at the same time.
        fetched = await asyncio.gather(*(fetch_repos(http, o) for o in orgs))

    # Each organization is saved in its own task, with its own session.
    saved = await asyncio.gather(*(save_org(o, repos) for o, repos in fetched))
    for (org, _), count in zip(fetched, saved):
        print(f"{org}: saved {count} repo snapshots")
    await engine.dispose()


def clean_names(names: list[str]) -> list[str]:
    """GitHub names are case-insensitive, so lowercase them and drop repeats.

    Without this, passing 'Vercel' and 'vercel' would create two organization rows,
    and passing the same name twice would make two concurrent tasks insert the same
    organization at once and crash on the unique constraint.
    """
    return list(dict.fromkeys(name.strip().lower() for name in names if name.strip()))


if __name__ == "__main__":
    orgs = clean_names(sys.argv[1:] or DEFAULT_ORGS)
    asyncio.run(run(orgs))