"""Database access. Two tables:

  problems     one row per problem, including its hidden testbench
  submissions  one row per run, linked to a problem

In Docker this talks to PostgreSQL (DATABASE_URL is set in docker-compose.yml).
Without that variable it falls back to a local SQLite file, which is handy for
running the tests without a database server.
"""
import os
import re
import time
from datetime import datetime, timezone

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, MetaData, String,
                        Table, Text, create_engine, delete, func, insert, select, update)
from sqlalchemy.exc import OperationalError

from .problems import PROBLEMS

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///judge.db")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
meta = MetaData()

problems = Table(
    "problems", meta,
    Column("id", Integer, primary_key=True),
    Column("slug", String(100), unique=True, nullable=False),   # short name used in URLs
    Column("title", String(100), nullable=False),
    Column("difficulty", String(10), nullable=False),
    Column("statement", Text, nullable=False),
    Column("starter", Text, nullable=False),
    Column("testbench", Text, nullable=False),
    Column("solution", Text),                                   # reference answer, never sent to the page
    Column("created_at", DateTime(timezone=True), nullable=False),
)

submissions = Table(
    "submissions", meta,
    Column("id", Integer, primary_key=True),
    Column("problem_id", Integer, ForeignKey("problems.id"), nullable=False, index=True),
    Column("code", Text, nullable=False),
    Column("verdict", String(20), nullable=False),
    Column("output", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    if dt.tzinfo is None:                   # SQLite drops the timezone; we always store UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def public(row) -> dict:
    """What the page is allowed to see: no testbench, no solution."""
    return {"id": row.slug, "title": row.title, "difficulty": row.difficulty,
            "statement": row.statement, "starter": row.starter}


def init():
    """Create the tables if missing and load the starter problems into an empty database."""
    for attempt in range(30):               # the database container may still be starting
        try:
            meta.create_all(engine)
            break
        except OperationalError:
            if attempt == 29:
                raise
            time.sleep(1)
    with engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(problems)).scalar() == 0:
            for p in PROBLEMS:
                conn.execute(insert(problems).values(
                    slug=p["id"], title=p["title"], difficulty=p["difficulty"],
                    statement=p["statement"], starter=p["starter"],
                    testbench=p["testbench"], created_at=_now()))


def list_problems() -> list:
    with engine.connect() as conn:
        return [public(r) for r in conn.execute(select(problems).order_by(problems.c.id))]


def get_problem(slug: str):
    """Full row (including the testbench) or None."""
    with engine.connect() as conn:
        return conn.execute(select(problems).where(problems.c.slug == slug)).first()


def add_problem(title, difficulty, statement, starter, testbench, solution) -> dict:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "problem"
    with engine.begin() as conn:
        slug, n = base, 1
        while conn.execute(select(problems.c.id).where(problems.c.slug == slug)).first():
            n += 1
            slug = f"{base}-{n}"
        conn.execute(insert(problems).values(
            slug=slug, title=title, difficulty=difficulty, statement=statement,
            starter=starter, testbench=testbench, solution=solution, created_at=_now()))
        return public(conn.execute(select(problems).where(problems.c.slug == slug)).first())


def add_submission(problem_pk: int, code: str, verdict: str, output: str) -> None:
    with engine.begin() as conn:
        conn.execute(insert(submissions).values(
            problem_id=problem_pk, code=code, verdict=verdict, output=output, created_at=_now()))


def list_submissions(problem_pk: int, limit: int = 20) -> list:
    query = (select(submissions).where(submissions.c.problem_id == problem_pk)
             .order_by(submissions.c.id.desc()).limit(limit))
    with engine.connect() as conn:
        return [{"id": r.id, "verdict": r.verdict, "code": r.code, "output": r.output,
                 "created_at": _iso(r.created_at)} for r in conn.execute(query)]


def update_problem(problem_pk: int, title, difficulty, statement, starter, testbench, solution) -> dict:
    """Changes a problem in place. Its short name (slug) stays the same so old links keep working."""
    with engine.begin() as conn:
        conn.execute(update(problems).where(problems.c.id == problem_pk).values(
            title=title, difficulty=difficulty, statement=statement,
            starter=starter, testbench=testbench, solution=solution))
        return public(conn.execute(select(problems).where(problems.c.id == problem_pk)).first())


def delete_problem(problem_pk: int) -> None:
    # Submissions point at their problem (foreign key), so they must go first.
    # Both deletes run in one transaction: either both happen or neither does.
    with engine.begin() as conn:
        conn.execute(delete(submissions).where(submissions.c.problem_id == problem_pk))
        conn.execute(delete(problems).where(problems.c.id == problem_pk))


def clear_submissions(problem_pk: int) -> None:
    with engine.begin() as conn:
        conn.execute(delete(submissions).where(submissions.c.problem_id == problem_pk))


def delete_submission(submission_id: int) -> bool:
    with engine.begin() as conn:
        return conn.execute(delete(submissions).where(submissions.c.id == submission_id)).rowcount > 0
