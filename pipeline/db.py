"""[A 담당] DB 저장·조회 함수.

함수 이름·입출력은 「시스템 운영·모듈 전달 가이드」 4-2와 같음.

중요: 이 파일의 함수는 conn.commit()을 하지 않음.
저장 확정(commit)·취소(rollback)는 C의 run.py가 한 번에 처리함.

- 접속 정보는 환경변수 DATABASE_URL에서만 읽음 (코드에 직접 쓰지 않음)
- observations는 (code, obs_date) 기준 upsert. 행을 삭제하는 함수는 두지 않음
  (FRED S&P500은 최근 10년치만 제공되므로, 한 번 저장한 과거 값을 지우지 않는 것이 원칙)
"""
from __future__ import annotations

import datetime as dt
import math
import os

import pandas as pd
import psycopg

REQUIRED_COLS = ["code", "obs_date", "value"]

UPSERT_SQL = (
    "INSERT INTO observations (code, obs_date, value, fetched_at) "
    "VALUES (%s, %s, %s, %s) "
    "ON CONFLICT (code, obs_date) DO UPDATE SET "
    "value = EXCLUDED.value, fetched_at = EXCLUDED.fetched_at"
)


def get_connection():
    """환경변수 DATABASE_URL로 Supabase PostgreSQL 연결을 열어 반환.

    prepare_threshold=None: Supabase 연결 풀러(pooler)를 쓸 때 생길 수 있는
    'prepared statement already exists' 오류를 피하기 위한 설정.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "환경변수 DATABASE_URL이 없습니다. "
            "C에게 받은 접속 주소로 export DATABASE_URL=\"...\" 를 먼저 실행하세요."
        )
    return psycopg.connect(url, prepare_threshold=None, connect_timeout=15)


def _clean_value(v):
    """NaN·None은 None(=DB의 NULL)으로, 나머지는 float로."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _to_date(v) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return pd.Timestamp(v).date()


def upsert_observations(conn, df: pd.DataFrame) -> int:
    """observations 테이블에 (code, obs_date) 기준 upsert. 저장 행 수 반환.

    fetched_at은 저장 시각(UTC)으로 채움. commit하지 않음.
    """
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"입력 표에 필요한 컬럼이 없습니다: {missing}")
    if df.empty:
        return 0

    data = df[REQUIRED_COLS].drop_duplicates(subset=["code", "obs_date"], keep="last")
    now_utc = dt.datetime.now(dt.timezone.utc)
    rows = [
        (str(code), _to_date(obs_date), _clean_value(value), now_utc)
        for code, obs_date, value in data.itertuples(index=False, name=None)
    ]
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
    return len(rows)


def load_observations(conn, start: str | None = None) -> pd.DataFrame:
    """observations를 읽어 code, obs_date, value 표로 반환 (B 계산 입력용).

    - start("YYYY-MM-DD")를 주면 그 날짜 이후만
    - value는 float (DB의 NULL은 NaN). 정렬: code, obs_date 오름차순
    """
    sql = "SELECT code, obs_date, value FROM observations"
    params: tuple = ()
    if start:
        dt.date.fromisoformat(start)          # 형식 확인
        sql += " WHERE obs_date >= %s"
        params = (start,)
    sql += " ORDER BY code, obs_date"

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    df = pd.DataFrame(rows, columns=["code", "obs_date", "value"])
    # DB numeric 값은 Decimal로 읽히므로 계산하기 쉬운 float로 변환
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("float64")
    return df
