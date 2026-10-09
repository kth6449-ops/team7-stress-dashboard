"""[C 담당] 조회 API (FastAPI).

현재 단계(10/12 임시 API): docs/api/samples 의 가상 JSON을 그대로 반환.
10/14 이후: 같은 응답 구조를 유지한 채 DB 조회로 교체.

로컬 실행:  uvicorn api.main:app --reload   →  http://127.0.0.1:8000/docs
"""
import datetime as dt
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

SAMPLES = Path(__file__).resolve().parent.parent / "docs" / "api" / "samples"

app = FastAPI(
    title="Team 7 금융시장 스트레스 API",
    version="0.1.0",
    description="임시 API — 모든 값은 가상 샘플 데이터(DEMO)입니다.",
)

# 화면(Vercel·로컬) 주소 허용. 운영 시 환경변수 ALLOWED_ORIGINS에 쉼표로 추가.
origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500").split(",")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in origins], allow_methods=["GET"])


def sample(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


def check_range(start: dt.date | None, end: dt.date | None) -> None:
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="from은 to보다 늦을 수 없습니다.")


def in_range(day: str, start: dt.date | None, end: dt.date | None) -> bool:
    d = dt.date.fromisoformat(day)
    return (start is None or d >= start) and (end is None or d <= end)


@app.get("/health")
def health():
    return sample("05_health.json")


@app.get("/scores/latest")
def scores_latest():
    return sample("01_scores_latest.json")


@app.get("/scores")
def scores(
    start: dt.date = Query(..., alias="from", description="시작일 YYYY-MM-DD (포함)"),
    end: dt.date = Query(..., alias="to", description="종료일 YYYY-MM-DD (포함)"),
):
    check_range(start, end)
    data = sample("02_scores_history.json")
    items = [i for i in data["items"] if in_range(i["as_of_date"], start, end)]
    return {"from": start.isoformat(), "to": end.isoformat(),
            "rule_version": data["rule_version"], "items": items}


@app.get("/indicators")
def indicators():
    return sample("03_indicators.json")


@app.get("/indicators/{code}/observations")
def observations(
    code: str,
    start: dt.date | None = Query(None, alias="from"),
    end: dt.date | None = Query(None, alias="to"),
):
    check_range(start, end)
    known = {i["code"]: i for i in sample("03_indicators.json")["items"]}
    if code not in known:
        raise HTTPException(status_code=404, detail=f"존재하지 않는 지표 코드입니다: {code}")
    data = sample("04_observations.json")
    items = data["items"] if code == data["code"] else []   # 샘플은 DEXKOUS만 보유
    items = [i for i in items if in_range(i["obs_date"], start, end)]
    return {"code": code, "unit": known[code]["unit"], "items": items}


@app.get("/methodology")
def methodology():
    return sample("07_methodology.json")
