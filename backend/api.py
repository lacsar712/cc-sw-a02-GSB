import math
import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post, put
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
DEFAULT_TOLERANCE_NM = 0.08
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS = {
    "calibrator": {"role": "writer", "password_hash": pwd.hash("calib123456")},
    "inspector": {"role": "reader", "password_hash": pwd.hash("insp123456")},
}

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id serial PRIMARY KEY,
        lamp text NOT NULL,
        nominal_nm double precision NOT NULL,
        measured_nm double precision NOT NULL,
        status text NOT NULL,
        verdict text NOT NULL DEFAULT '',
        reason text NOT NULL DEFAULT '',
        created_by text NOT NULL,
        created_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tolerance_state (
        id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        tolerance_nm double precision NOT NULL,
        updated_by text NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tolerance_changes (
        id serial PRIMARY KEY,
        old_nm double precision,
        new_nm double precision NOT NULL,
        changed_by text NOT NULL,
        changed_at timestamptz NOT NULL
    )
    """,
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tolerance_nm double precision",
]


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


class LoginIn(BaseModel):
    username: str
    password: str


class JobIn(BaseModel):
    lamp: str
    nominal_nm: float
    measured_nm: float


class ToleranceIn(BaseModel):
    tolerance_nm: float


def user_from_request(request: Request) -> dict:
    auth = request.headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = jwt.decode(auth[7:], SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌") from exc
    if payload.get("sub") not in USERS:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="无效令牌")
    return {"username": payload["sub"], "role": payload.get("role")}


@get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "spectrum-wavelength-desk"}


@post("/api/login")
async def login(data: LoginIn) -> dict:
    u = USERS.get(data.username)
    if not u or not pwd.verify(data.password, u["password_hash"]):
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    token = jwt.encode(
        {
            "sub": data.username,
            "role": u["role"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=12),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"access_token": token, "role": u["role"], "username": data.username}


@get("/api/jobs")
async def list_jobs(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, tolerance_nm, created_by FROM jobs ORDER BY id DESC"
        ).fetchall()
        return list(rows)


@get("/api/jobs/{job_id:int}")
async def get_job(request: Request, job_id: int) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            "SELECT id, lamp, nominal_nm, measured_nm, status, verdict, reason, tolerance_nm, created_by FROM jobs WHERE id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="任务不存在")
        return dict(row)


@post("/api/jobs")
async def create_job(request: Request, data: JobIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可提交")
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, created_by, created_at)
            VALUES (%s,%s,%s,'pending','','',%s,%s) RETURNING id
            """,
            (data.lamp.strip(), data.nominal_nm, data.measured_nm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
        return {"id": row["id"], "status": "pending"}


@get("/api/tolerance")
async def get_tolerance(request: Request) -> dict:
    user_from_request(request)
    with connect() as conn:
        row = conn.execute(
            "SELECT tolerance_nm, updated_by, updated_at FROM tolerance_state WHERE id = 1"
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="允差档未初始化")
        return dict(row)


@get("/api/tolerance/changes")
async def list_tolerance_changes(request: Request) -> list:
    user_from_request(request)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, old_nm, new_nm, changed_by, changed_at FROM tolerance_changes ORDER BY id DESC LIMIT 100"
        ).fetchall()
        return list(rows)


@put("/api/tolerance")
async def update_tolerance(request: Request, data: ToleranceIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可改档")
    val = data.tolerance_nm
    if not math.isfinite(val) or val <= 0 or val > 1000:
        raise HTTPException(status_code=400, detail="允差需为 0 到 1000 nm 之间的正数")
    now = datetime.now(timezone.utc)
    with connect() as conn:
        cur = conn.execute(
            "SELECT tolerance_nm FROM tolerance_state WHERE id = 1 FOR UPDATE"
        ).fetchone()
        old = cur["tolerance_nm"] if cur else None
        if cur:
            conn.execute(
                "UPDATE tolerance_state SET tolerance_nm=%s, updated_by=%s, updated_at=%s WHERE id = 1",
                (val, user["username"], now),
            )
        else:
            conn.execute(
                "INSERT INTO tolerance_state(id, tolerance_nm, updated_by, updated_at) VALUES (1,%s,%s,%s)",
                (val, user["username"], now),
            )
        conn.execute(
            "INSERT INTO tolerance_changes(old_nm, new_nm, changed_by, changed_at) VALUES (%s,%s,%s,%s)",
            (old, val, user["username"], now),
        )
        conn.commit()
    return {"tolerance_nm": val, "updated_by": user["username"], "updated_at": now}


def on_startup() -> None:
    with connect() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        row = conn.execute("SELECT tolerance_nm FROM tolerance_state WHERE id = 1").fetchone()
        if not row:
            now = datetime.now(timezone.utc)
            conn.execute(
                "INSERT INTO tolerance_state(id, tolerance_nm, updated_by, updated_at) VALUES (1,%s,'system',%s)",
                (DEFAULT_TOLERANCE_NM, now),
            )
            conn.execute(
                "INSERT INTO tolerance_changes(old_nm, new_nm, changed_by, changed_at) VALUES (NULL,%s,'system',%s)",
                (DEFAULT_TOLERANCE_NM, now),
            )
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            now = datetime.now(timezone.utc)
            conn.execute(
                """
                INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, tolerance_nm, created_by, created_at)
                VALUES
                ('氦灯-587', 587.56, 587.50, 'done', '合格', '偏差 0.0600 nm 在允差 0.08 nm 内', 0.08, 'seed', %s),
                ('汞灯-546', 546.07, 546.30, 'done', '超差', '偏差 0.2300 nm 超过允差 0.08 nm', 0.08, 'seed', %s)
                """,
                (now, now),
            )
        conn.commit()


app = Litestar(
    route_handlers=[
        health,
        login,
        list_jobs,
        get_job,
        create_job,
        get_tolerance,
        list_tolerance_changes,
        update_tolerance,
    ],
    on_startup=[on_startup],
)
