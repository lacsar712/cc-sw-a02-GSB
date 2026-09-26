import math
import os
from datetime import datetime, timedelta, timezone

import psycopg
from jose import JWTError, jwt
from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from passlib.context import CryptContext
from psycopg.rows import dict_row
from pydantic import BaseModel

from domain import DEFAULT_TOLERANCE_NM

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")
SECRET = os.environ.get("JWT_SECRET", "spectrum-dev-secret")
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
CREATE TABLE IF NOT EXISTS tolerance_tiers (
    id serial PRIMARY KEY,
    tolerance_nm double precision NOT NULL,
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
        history = conn.execute(
            "SELECT id, tolerance_nm, changed_by, changed_at FROM tolerance_tiers ORDER BY id DESC"
        ).fetchall()
        return {"current": history[0] if history else None, "history": list(history)}


@post("/api/tolerance")
async def change_tolerance(request: Request, data: ToleranceIn) -> dict:
    user = user_from_request(request)
    if user["role"] != "writer":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="仅校准员可改档")
    if not math.isfinite(data.tolerance_nm) or data.tolerance_nm <= 0:
        raise HTTPException(status_code=400, detail="档位必须为正的有限数值")
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO tolerance_tiers(tolerance_nm, changed_by, changed_at)
            VALUES (%s,%s,%s)
            RETURNING id, tolerance_nm, changed_by, changed_at
            """,
            (data.tolerance_nm, user["username"], datetime.now(timezone.utc)),
        ).fetchone()
        conn.commit()
        return dict(row)


def on_startup() -> None:
    with connect() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        n_tiers = conn.execute("SELECT COUNT(*) AS n FROM tolerance_tiers").fetchone()["n"]
        now = datetime.now(timezone.utc)
        if n_tiers == 0:
            conn.execute(
                "INSERT INTO tolerance_tiers(tolerance_nm, changed_by, changed_at) VALUES (%s,'seed',%s)",
                (DEFAULT_TOLERANCE_NM, now),
            )
        n = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        if n == 0:
            conn.execute(
                """
                INSERT INTO jobs(lamp, nominal_nm, measured_nm, status, verdict, reason, tolerance_nm, created_by, created_at)
                VALUES
                ('氦灯-587', 587.56, 587.50, 'done', '合格', '偏差 0.0600 nm 在允差 0.08 内', 0.08, 'seed', %s),
                ('汞灯-546', 546.07, 546.30, 'done', '超差', '偏差 0.2300 nm 超过允差 0.08', 0.08, 'seed', %s)
                """,
                (now, now),
            )
        conn.commit()


app = Litestar(
    route_handlers=[health, login, list_jobs, get_job, create_job, get_tolerance, change_tolerance],
    on_startup=[on_startup],
)
