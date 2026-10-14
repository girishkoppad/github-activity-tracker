import httpx
import pytest
from sqlalchemy import event, func, select

import ingestion
from database import SessionLocal, engine
from main import app
from models import Organization, RepoSnapshot


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def github_repo(name: str, stars: int, language: str | None = "Python") -> dict:
    """A fake item shaped like GitHub's real API response."""
    return {
        "name": name,
        "language": language,
        "stargazers_count": stars,
        "forks_count": 1,
        "open_issues_count": 2,
    }


async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unknown_organization_is_404(client):
    response = await client.get("/organizations/nobody")
    assert response.status_code == 404


async def test_organization_lookup_ignores_case(client):
    await ingestion.save_org("acme", [github_repo("a", 5)])
    response = await client.get("/organizations/ACME")
    assert response.status_code == 200
    assert response.json()["login"] == "acme"


async def test_save_org_twice_keeps_history_but_one_organization():
    await ingestion.save_org("acme", [github_repo("a", 5), github_repo("b", 7)])
    await ingestion.save_org("acme", [github_repo("a", 6), github_repo("b", 8)])
    async with SessionLocal() as db:
        orgs = await db.scalar(select(func.count()).select_from(Organization))
        snapshots = await db.scalar(select(func.count()).select_from(RepoSnapshot))
    assert orgs == 1
    assert snapshots == 4  # 2 repos x 2 runs: old rows are kept as history


async def test_save_org_with_no_repos_does_nothing():
    assert await ingestion.save_org("empty", []) == 0
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(Organization)) == 0


async def test_api_shows_only_the_newest_snapshot_of_each_repo(client):
    await ingestion.save_org("acme", [github_repo("a", 10)])
    await ingestion.save_org("acme", [github_repo("a", 99)])  # a later run

    repos = (await client.get("/repos")).json()
    assert len(repos) == 1
    assert repos[0]["stars"] == 99
    assert repos[0]["organization"] == "acme"

    org = (await client.get("/organizations/acme")).json()
    assert [s["stars"] for s in org["snapshots"]] == [99]


async def test_repos_are_sorted_by_stars_and_filterable(client):
    await ingestion.save_org(
        "acme",
        [github_repo("low", 1), github_repo("high", 500), github_repo("go-tool", 50, "Go")],
    )
    names = [r["repo_name"] for r in (await client.get("/repos")).json()]
    assert names == ["high", "go-tool", "low"]

    only_go = (await client.get("/repos", params={"language": "go"})).json()
    assert [r["repo_name"] for r in only_go] == ["go-tool"]

    popular = (await client.get("/repos", params={"min_stars": 100})).json()
    assert [r["repo_name"] for r in popular] == ["high"]


async def test_paging(client):
    await ingestion.save_org("acme", [github_repo(f"r{i}", i) for i in range(1, 6)])
    page = (await client.get("/repos", params={"limit": 2, "offset": 2})).json()
    assert [r["stars"] for r in page] == [3, 2]


@pytest.mark.parametrize("params", [{"limit": 500}, {"limit": 0}, {"min_stars": -1}, {"offset": -1}])
async def test_bad_query_values_are_rejected(client, params):
    assert (await client.get("/repos", params=params)).status_code == 422


async def test_listing_organizations_does_not_cause_n_plus_one(client):
    """The number of SQL statements must NOT grow with the number of organizations."""
    for name in ["a", "b", "c", "d", "e"]:
        await ingestion.save_org(name, [github_repo("x", 1), github_repo("y", 2)])
    await client.get("/organizations")  # warm-up: opens the first connection

    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        response = await client.get("/organizations")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert len(response.json()) == 5
    assert len(statements) == 2  # 1 for organizations + 1 for ALL their snapshots


def test_clean_names_lowercases_and_removes_repeats():
    assert ingestion.clean_names(["Vercel", "vercel", " FastAPI ", ""]) == ["vercel", "fastapi"]


async def test_deleting_an_organization_deletes_its_snapshots():
    await ingestion.save_org("acme", [github_repo("a", 1)])
    async with SessionLocal() as db:
        org = await db.scalar(select(Organization))
        await db.delete(org)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(RepoSnapshot)) == 0