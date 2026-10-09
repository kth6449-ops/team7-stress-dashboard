"""[A 담당] DB 저장·조회 함수.

함수 이름·입출력은 「시스템 운영·모듈 전달 가이드」 4-2와 같아야 함.
중요: 함수 안에서 conn.commit()을 하지 않음. 저장 확정은 run.py(C)가 한 번에 처리.
"""
import pandas as pd


def get_connection():
    """환경변수 DATABASE_URL로 PostgreSQL 연결을 열어 반환."""
    raise NotImplementedError("A 전달본으로 교체 예정")


def upsert_observations(conn, df: pd.DataFrame) -> int:
    """observations에 (code, obs_date) 기준 upsert. 저장 행 수 반환.
    fetched_at은 저장 시각(UTC). commit하지 않음."""
    raise NotImplementedError("A 전달본으로 교체 예정")


def load_observations(conn, start: str | None = None) -> pd.DataFrame:
    """observations를 code, obs_date, value 표로 반환 (B 계산 입력용)."""
    raise NotImplementedError("A 전달본으로 교체 예정")
