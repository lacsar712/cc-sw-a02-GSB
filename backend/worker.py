import os
import time

import psycopg
from psycopg.rows import dict_row

from domain import DEFAULT_TOLERANCE_NM, judge

DSN = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:54395/spectrum")


def connect():
    return psycopg.connect(DSN, row_factory=dict_row)


def claim_one(conn):
    # 单条语句同一快照锁单并记下现行档：领走那一刻的档即判定档
    row = conn.execute(
        """
        SELECT j.id, j.nominal_nm, j.measured_nm,
               (SELECT t.tolerance_nm FROM tolerance_tiers t ORDER BY t.id DESC LIMIT 1) AS tolerance_nm
        FROM jobs j
        WHERE j.status='pending'
        ORDER BY j.id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    tolerance_nm = row["tolerance_nm"]
    if tolerance_nm is None:
        tolerance_nm = DEFAULT_TOLERANCE_NM
    verdict, reason = judge(row["nominal_nm"], row["measured_nm"], tolerance_nm)
    conn.execute(
        "UPDATE jobs SET status='done', verdict=%s, reason=%s, tolerance_nm=%s WHERE id=%s",
        (verdict, reason, tolerance_nm, row["id"]),
    )
    conn.commit()
    return row["id"]


def main():
    while True:
        try:
            with connect() as conn:
                claim_one(conn)
        except Exception as exc:
            print("worker err", exc, flush=True)
        time.sleep(0.4)


if __name__ == "__main__":
    main()
