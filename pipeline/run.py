"""[C 담당] 수집 → 계산 → 저장 통합 실행.

실행 예:
    python -m pipeline.run --start 2005-01-01   # 최초 전체 적재
    python -m pipeline.run --days 14            # 매일 갱신 (기본값)

원칙:
- 실행 기록(pipeline_runs)은 별도로 즉시 저장 → 실패해도 기록이 남음
- 원본 저장·점수 저장은 하나의 트랜잭션 → 중간 실패 시 전부 취소, 마지막 정상 결과 유지
- 점수는 매 실행마다 전체 기간 재계산 (재수집으로 과거 값이 바뀔 수 있으므로)
"""
import argparse
import datetime as dt
import sys
import traceback

import pandas as pd

from pipeline import collect, db, scoring


def _rows(df: pd.DataFrame, cols: list[str]) -> list[tuple]:
    """DataFrame을 DB 입력용 튜플 목록으로 변환. NaN은 None(=NULL)으로."""
    clean = df[cols].astype(object).where(df[cols].notna(), None)
    return [tuple(r) for r in clean.itertuples(index=False, name=None)]


def start_run(conn, trigger: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (trigger, started_at, status) "
            "VALUES (%s, now(), 'running') RETURNING run_id",
            (trigger,),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def finish_run(conn, run_id: int, status: str, rows: int = 0, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE pipeline_runs SET finished_at = now(), status = %s, "
            "rows_written = %s, error = %s WHERE run_id = %s",
            (status, rows, error, run_id),
        )
    conn.commit()


IND_COLS = ["code", "as_of_date", "rule_version", "stress_value", "percentile", "score"]
DAILY_COLS = [
    "as_of_date", "rule_version", "equity_score", "fx_score", "rate_score", "credit_score",
    "total_score", "total_percentile", "stage", "spread_count", "is_provisional",
]


def save_scores(conn, ind: pd.DataFrame, daily: pd.DataFrame, run_id: int) -> int:
    """계산 결과 저장. commit하지 않음 (main에서 한 번에 확정)."""
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO indicator_score ({', '.join(IND_COLS)}, computed_at) "
            f"VALUES ({', '.join(['%s'] * len(IND_COLS))}, now()) "
            "ON CONFLICT (code, as_of_date, rule_version) DO UPDATE SET "
            "stress_value = EXCLUDED.stress_value, percentile = EXCLUDED.percentile, "
            "score = EXCLUDED.score, computed_at = EXCLUDED.computed_at",
            _rows(ind, IND_COLS),
        )
        update_cols = [c for c in DAILY_COLS if c not in ("as_of_date", "rule_version")]
        cur.executemany(
            f"INSERT INTO daily_scores ({', '.join(DAILY_COLS)}, computed_at, run_id) "
            f"VALUES ({', '.join(['%s'] * len(DAILY_COLS))}, now(), {int(run_id)}) "
            "ON CONFLICT (as_of_date, rule_version) DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
            + ", computed_at = EXCLUDED.computed_at, run_id = EXCLUDED.run_id",
            _rows(daily, DAILY_COLS),
        )
    return len(ind) + len(daily)


def main() -> int:
    parser = argparse.ArgumentParser(description="Team 7 데이터 파이프라인")
    parser.add_argument("--start", help="수집 시작일 YYYY-MM-DD (지정 시 --days 무시)")
    parser.add_argument("--days", type=int, default=14, help="최근 N일 재수집 (기본 14)")
    parser.add_argument("--trigger", default="manual", choices=["manual", "schedule"])
    args = parser.parse_args()

    start = args.start or (dt.date.today() - dt.timedelta(days=args.days)).isoformat()

    conn = db.get_connection()
    run_id = start_run(conn, args.trigger)
    try:
        obs = collect.fetch_observations(collect.SERIES, start)
        written = db.upsert_observations(conn, obs)

        all_obs = db.load_observations(conn)          # 같은 트랜잭션: 방금 저장한 값 포함
        ind, daily = scoring.compute_scores(all_obs)
        written += save_scores(conn, ind, daily, run_id)

        conn.commit()                                  # 여기서 한 번에 확정
        finish_run(conn, run_id, "success", written)
        print(f"[run {run_id}] success: {written} rows")
        return 0
    except Exception as e:  # noqa: BLE001 - 어떤 오류든 기록 후 종료
        conn.rollback()                                # 이번 실행의 저장 전부 취소
        finish_run(conn, run_id, "failed", 0, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
