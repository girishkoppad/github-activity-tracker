# GitHub Activity Tracker

An async data-ingestion engine and REST API. It fetches repository data for GitHub organizations
concurrently, stores timestamped snapshots in PostgreSQL, and serves the newest data through FastAPI.

## Why it exists
Star counts change daily. Each ingestion run stores a new snapshot instead of overwriting, so
history is kept, and the API always shows the latest value per repo.

## Architecture
```mermaid
flowchart LR
    GH[GitHub API] -->|aiohttp, concurrent| ING[ingestion.py]
    ING -->|SQLAlchemy async| DB[(PostgreSQL)]
    DB --> API[FastAPI main.py]
    API --> USER[/docs, curl, apps/]
```

## Results (measured on my machine)
- Fetching 5 orgs sequentially (5 separate runs): **10.6 s**; concurrently with asyncio (1 run): **2.7 s** (~3.9x faster)
- `GET /repos?limit=20`: **~14 ms** median warm (local machine; first request after start ~0.3-0.6 s while connections open)
- **15 automated tests** against a separate test database

## Design decisions
- **Snapshots, not overwrites:** history is preserved; a window function (`row_number()`) returns only the newest row per repo.
- **No N+1 queries:** `selectinload` loads all snapshots in one extra query; a test asserts exactly 2 SQL statements.
- **One DB session per concurrent task:** async sessions can't be shared.
- **Secrets in `.env`**, never committed.

## Endpoints
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/organizations` | All orgs with latest snapshot per repo |
| GET | `/organizations/{login}` | One org, 404 if unknown |
| GET | `/repos?language=&min_stars=&limit=&offset=` | Filtered, paginated repos |

## Run it
1. Install Python 3.14+ and PostgreSQL18; create a database `github_tracker`.
2. `python -m venv venv` then `venv\Scripts\activate` then `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in `DATABASE_URL` (and optionally `GITHUB_TOKEN`).
4. `python create_tables.py`
5. `python ingestion.py vercel fastapi supabase`
6. `uvicorn main:app --reload` and open http://127.0.0.1:8000/docs
7. Tests: `pip install -r requirements-dev.txt` then `pytest`

## Known limitations
- Only the first 100 repos per organization are fetched (no pagination of GitHub's API yet).
- No scheduler: ingestion is run manually.
- No retry/backoff on rate limits.

## Possible next steps
Pagination of GitHub results, scheduled runs, Docker, a trend endpoint (stars over time).