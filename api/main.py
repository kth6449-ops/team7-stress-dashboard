"""[C 담당] 조회 API (FastAPI).

Supabase(PostgreSQL)에 저장된 결과를 읽어서 반환한다 (읽기 전용).
- 응답 구조는 docs/api/API_규격_정의서.md 와 같음 (10/12 임시 API의 샘플 JSON과 동일한 필드)
- 이용자 요청 때 FRED 호출·점수 재계산을 하지 않음. 파이프라인(run.py)이 저장한 값만 조회
- 기여도(contributions)와 지표 변화량(changes)만 API에서 계산 (B 산식 결과를 바꾸지 않음)

로컬 실행:  uvicorn api.main:app --reload   →  http://127.0.0.1:8000/docs
환경변수:   DATABASE_URL(필수), ALLOWED_ORIGINS(쉼표 구분), STALE_DAYS(기본 10)
"""
import datetime as dt
import logging
import math
import os
from contextlib import contextmanager
from decimal import Decimal

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pipeline import db
from pipeline.scoring import CONFIG, MARKETS, RULE_VERSION, SERIES

log = logging.getLogger("api")

app = FastAPI(
    title="Team 7 금융시장 스트레스 API",
    version="0.2.0",
    description="Supabase에 저장된 FRED 원본·스트레스 점수를 조회하는 읽기 전용 API",
)

# 화면(Vercel·로컬) 주소 허용. 운영 시 환경변수 ALLOWED_ORIGINS에 쉼표로 추가.
origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500").split(",")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in origins], allow_methods=["GET"])

# /health 갱신 지연 기준(일): 한국 날짜 - 최신 점수 기준일 > STALE_DAYS 이면 stale.
# 결정 3-B(실측 최대 공개 지연 + 2일): 원/달러 최대 8일(A_check_report, 10/10 실측) + 2 = 10
STALE_DAYS = int(os.getenv("STALE_DAYS", "10"))
KST = dt.timezone(dt.timedelta(hours=9))

# 변화량 비교 시점(유효 관측치 개수)과 단위. %는 변화율, %p·pt는 차이
CHANGE_LAGS = {"d1": 1, "m1": 21, "m3": 63}
CHANGE_UNIT = {"DEXKOUS": "%", "SP500": "%", "DGS10": "%p", "BAA10Y": "%p", "VIXCLS": "pt"}
MARKET_KEYS = list(MARKETS)  # equity, fx, rate, credit


@app.exception_handler(psycopg.Error)
async def db_error(request: Request, exc: psycopg.Error):
    # DB 주소·내부 오류 내용은 응답에 노출하지 않고 서버 로그에만 남김
    log.exception("DB 오류: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "서버 처리 중 오류가 발생했습니다."})


@contextmanager
def cursor():
    """요청마다 연결을 열고 닫음 (무료 티어 저트래픽 기준, 읽기 전용)."""
    conn = db.get_connection()
    try:
        conn.read_only = True
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def num(v):
    """DB numeric(Decimal) → float. NULL·NaN·inf → None."""
    if v is None:
        return None
    f = float(v) if isinstance(v, Decimal) else v
    return f if isinstance(f, (int, float)) and math.isfinite(f) else None


def utc_z(t: dt.datetime | None) -> str | None:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def check_range(start: dt.date | None, end: dt.date | None) -> None:
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="from은 to보다 늦을 수 없습니다.")


def contributions(markets: dict, total) -> dict:
    """시장별 기여율(%). 종합점수가 0(또는 없음)이면 모두 null."""
    if not total:
        return {k: None for k in MARKET_KEYS}
    return {k: (markets[k] / total * 100 if markets[k] is not None else None) for k in MARKET_KEYS}


@app.get("/health")
def health():
    with cursor() as cur:
        cur.execute("SELECT max(as_of_date) FROM daily_scores WHERE rule_version = %s", (RULE_VERSION,))
        latest = cur.fetchone()[0]
        cur.execute("SELECT max(finished_at) FROM pipeline_runs WHERE status = 'success'")
        last_success = cur.fetchone()[0]
    if latest is None:
        status = "empty"
    else:
        today_kst = dt.datetime.now(KST).date()
        status = "stale" if (today_kst - latest).days > STALE_DAYS else "fresh"
    return {
        "status": "ok",
        "data_status": status,
        "latest_as_of_date": latest.isoformat() if latest else None,
        "last_success_at": utc_z(last_success) if latest else None,
    }


@app.get("/scores/latest")
def scores_latest():
    with cursor() as cur:
        cur.execute(
            "SELECT as_of_date, equity_score, fx_score, rate_score, credit_score, total_score, "
            "total_percentile, stage, spread_count, is_provisional, computed_at "
            "FROM daily_scores WHERE rule_version = %s AND total_score IS NOT NULL "
            "ORDER BY as_of_date DESC LIMIT 1",
            (RULE_VERSION,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="조회 가능한 데이터가 없습니다.")
    (as_of, eq, fx, rate, credit, total, pct, stage, spread, prov, computed) = row
    markets = {"equity": num(eq), "fx": num(fx), "rate": num(rate), "credit": num(credit)}
    total = num(total)
    return {
        "as_of_date": as_of.isoformat(),
        "rule_version": RULE_VERSION,
        "total_score": total,
        "total_percentile": num(pct),
        "stage": stage,
        "markets": markets,
        "contributions": contributions(markets, total),
        "spread_count": spread,
        "is_provisional": prov,
        "computed_at": utc_z(computed),
    }


@app.get("/scores")
def scores(
    start: dt.date = Query(..., alias="from", description="시작일 YYYY-MM-DD (포함)"),
    end: dt.date = Query(..., alias="to", description="종료일 YYYY-MM-DD (포함)"),
):
    check_range(start, end)
    with cursor() as cur:
        # 계산 결과가 없는 날짜는 빠짐 (0점·보간 없음)
        cur.execute(
            "SELECT as_of_date, total_score, equity_score, fx_score, rate_score, credit_score "
            "FROM daily_scores WHERE rule_version = %s AND as_of_date BETWEEN %s AND %s "
            "AND total_score IS NOT NULL AND equity_score IS NOT NULL AND fx_score IS NOT NULL "
            "AND rate_score IS NOT NULL AND credit_score IS NOT NULL "
            "ORDER BY as_of_date",
            (RULE_VERSION, start, end),
        )
        rows = cur.fetchall()
    items = [
        {"as_of_date": d.isoformat(), "total_score": num(t),
         "markets": {"equity": num(eq), "fx": num(fx), "rate": num(rate), "credit": num(cr)}}
        for d, t, eq, fx, rate, cr in rows
    ]
    return {"from": start.isoformat(), "to": end.isoformat(), "rule_version": RULE_VERSION, "items": items}


def changes(code: str, values: list[float]) -> dict:
    """values: 유효 관측치를 최신순으로. N개 전 관측치가 없으면 null."""
    out = {}
    for key, lag in CHANGE_LAGS.items():
        if len(values) <= lag:
            out[key] = None
            continue
        now, prev = values[0], values[lag]
        if CHANGE_UNIT[code] == "%":
            out[key] = (now / prev - 1) * 100 if prev else None
        else:
            out[key] = now - prev
    return out


@app.get("/indicators")
def indicators():
    max_lag = max(CHANGE_LAGS.values())
    with cursor() as cur:
        cur.execute("SELECT code, name, market, unit, source_url FROM indicators")
        meta = {r[0]: r[1:] for r in cur.fetchall()}
        # 지표별 최근 유효 관측치(결측 제외) max_lag+1개
        cur.execute(
            "SELECT code, obs_date, value FROM ("
            "  SELECT code, obs_date, value, "
            "         row_number() OVER (PARTITION BY code ORDER BY obs_date DESC) AS rn "
            "  FROM observations WHERE value IS NOT NULL"
            ") t WHERE rn <= %s ORDER BY code, obs_date DESC",
            (max_lag + 1,),
        )
        recent: dict[str, list] = {}
        for code, d, v in cur.fetchall():
            recent.setdefault(code, []).append((d, num(v)))
        cur.execute("SELECT max(fetched_at) FROM observations")
        updated = cur.fetchone()[0]

    items = []
    for code in SERIES:
        name, market, unit, source_url = meta[code]
        obs = recent.get(code, [])
        items.append({
            "code": code,
            "name": name,
            "market": market,
            "unit": unit,
            "obs_date": obs[0][0].isoformat() if obs else None,
            "value": obs[0][1] if obs else None,
            "changes": changes(code, [v for _, v in obs]),
            "change_unit": CHANGE_UNIT[code],
            "source_url": source_url,
        })
    return {"items": items, "updated_at": utc_z(updated)}


@app.get("/indicators/{code}/observations")
def observations(
    code: str,
    start: dt.date | None = Query(None, alias="from"),
    end: dt.date | None = Query(None, alias="to"),
):
    check_range(start, end)
    with cursor() as cur:
        cur.execute("SELECT unit FROM indicators WHERE code = %s", (code,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"존재하지 않는 지표 코드입니다: {code}")
        # 휴장 등 결측일은 value: null로 포함
        cur.execute(
            "SELECT obs_date, value FROM observations WHERE code = %s "
            "AND (%s::date IS NULL OR obs_date >= %s) AND (%s::date IS NULL OR obs_date <= %s) "
            "ORDER BY obs_date",
            (code, start, start, end, end),
        )
        items = [{"obs_date": d.isoformat(), "value": num(v)} for d, v in cur.fetchall()]
    return {"code": code, "unit": row[0], "items": items}


@app.get("/methodology")
def methodology():
    return {
        "rule_version": RULE_VERSION,
        "indicators": SERIES,
        "market_weights": {k: 0.25 for k in MARKET_KEYS},
        "percentile_window_years": CONFIG["window_years_max"],
        "risk_stage_thresholds": CONFIG["stage_thresholds"],
        "spread_threshold": CONFIG["spread_threshold"],
    }
