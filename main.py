from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import AliasPath, BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from database import get_db
from models import Organization, RepoSnapshot

app = FastAPI(title="GitHub Activity Tracker")

# Every ingestion run adds NEW snapshot rows, so one repo has many rows over time.
# The API should show only the newest row of each repo. row_number() numbers the
# rows of each repo from newest (1) to oldest; we keep only the rows numbered 1.
_ranked = select(
    RepoSnapshot.id,
    func.row_number()
    .over(
        partition_by=(RepoSnapshot.organization_id, RepoSnapshot.repo_name),
        order_by=(RepoSnapshot.recorded_at.desc(), RepoSnapshot.id.desc()),
    )
    .label("rn"),
).subquery()
LATEST_IDS = select(_ranked.c.id).where(_ranked.c.rn == 1)


    
class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repo_name: str
    language: str | None
    stars: int
    forks: int
    open_issues: int
    recorded_at: datetime


class RepoOut(SnapshotOut):
    # Reads snapshot.organization.login, so you can tell whose repo it is.
    organization: str = Field(validation_alias=AliasPath("organization", "login"))


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    login: str
    snapshots: list[SnapshotOut]


def latest_snapshots():
    """Load each organization's snapshots, but only the newest one per repo."""
    return selectinload(Organization.snapshots.and_(RepoSnapshot.id.in_(LATEST_IDS)))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(db: AsyncSession = Depends(get_db)):
    # selectinload fetches all snapshots in ONE extra query (avoids the N+1 problem).
    stmt = select(Organization).options(latest_snapshots()).order_by(Organization.login)
    result = await db.execute(stmt)
    return result.scalars().all()


@app.get("/organizations/{login}", response_model=OrganizationOut)
async def get_organization(login: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Organization)
        .where(Organization.login == login.lower())
        .options(latest_snapshots())
    )
    organization = (await db.execute(stmt)).scalar_one_or_none()
    if organization is None:
        raise HTTPException(status_code=404, detail=f"Organization '{login}' not found")
    return organization


@app.get("/repos", response_model=list[RepoOut])
async def list_repos(
    language: str | None = None,
    min_stars: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(RepoSnapshot)
        .options(joinedload(RepoSnapshot.organization))
        .where(RepoSnapshot.id.in_(LATEST_IDS), RepoSnapshot.stars >= min_stars)
    )
    if language:
        stmt = stmt.where(func.lower(RepoSnapshot.language) == language.lower())
    stmt = stmt.order_by(RepoSnapshot.stars.desc(), RepoSnapshot.id).limit(limit).offset(offset)
    return (await db.execute(stmt)).scalars().all()