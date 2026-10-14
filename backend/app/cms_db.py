"""One place that talks to CMS Postgres.

DealMate used to have three copies of the same fetch (direct URL, docker exec,
ad-hoc SQL). When this app sits next to CMS they share a Docker network and
``DATABASE_URL`` is the only path that belongs in production. ``docker exec``
stays as a local-dev fallback when Postgres is not published to the host.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from typing import Any

log = logging.getLogger("lcdealmate.cms_db")

DEFAULT_DOCKER = "cms-uat-postgres-uat-1"
DEFAULT_DOCKER_USER = "cms_app_uat"
DEFAULT_DOCKER_DB = "cms_uat"


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def docker_container() -> str:
    """Docker exec is a local-dev fallback only.

    If ``DATABASE_URL`` is set (the CMS-network production path), do not fall
    back to ``docker exec`` unless ``CMS_PG_DOCKER`` is set explicitly — a
    DealMate container on ``cms-uat-net`` has no Docker socket.
    An empty ``CMS_PG_DOCKER=`` disables the fallback.
    """
    explicit = os.getenv("CMS_PG_DOCKER")
    if explicit is not None:
        return explicit.strip()
    if database_url():
        return ""
    return DEFAULT_DOCKER


def configured() -> bool:
    return bool(database_url() or docker_container())


def require_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("That is not a valid contract id") from exc


def _psycopg_json(sql: str, params: tuple[Any, ...] | None = None) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url(), connect_timeout=8, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
    if not row:
        return None
    return row.get("json_build_object") or next(iter(row.values()))


def _docker_sql(sql: str) -> Any:
    container = docker_container()
    if not container:
        raise RuntimeError("CMS_PG_DOCKER is not set")
    user = os.getenv("CMS_PG_USER", DEFAULT_DOCKER_USER)
    database = os.getenv("CMS_PG_DATABASE", DEFAULT_DOCKER_DB)
    proc = subprocess.run(
        [
            "docker", "exec", "-i", container, "psql",
            "-U", user, "-d", database, "-t", "-A", "-v", "ON_ERROR_STOP=1",
        ],
        input=sql,
        capture_output=True,
        text=True,
        timeout=45,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"docker exec {container} failed: {err[:500]}")
    text = (proc.stdout or "").strip()
    if not text or text == "null":
        return None
    return json.loads(text)


def fetch_json(sql: str, params: tuple[Any, ...] | None = None) -> tuple[Any, str]:
    """Run a query that returns one JSON value (``json_build_object`` / ``json_agg``).

    Prefers ``DATABASE_URL``. Falls back to docker exec only when that fails or
    is unset — never the other way around, so a containerised DealMate on the
    CMS network does not shell out to docker.
    """
    url = database_url()
    last_error: Exception | None = None
    if url:
        try:
            return _psycopg_json(sql, params), "database"
        except Exception as exc:
            last_error = exc
            log.warning("DATABASE_URL query failed: %s", exc)
            if not docker_container():
                raise

    if not docker_container():
        raise RuntimeError("No CMS database configured (set DATABASE_URL)") from last_error

    docker_sql = sql
    if params:
        bound: list[str] = []
        for value in params:
            if value is None:
                bound.append("NULL")
            else:
                bound.append("'" + require_uuid(str(value)) + "'")
        for literal in bound:
            docker_sql = docker_sql.replace("%s", literal, 1)
    return _docker_sql(docker_sql), "docker"
