"""[A 담당] FRED 데이터 수집.

함수 이름·입출력은 「시스템 운영·모듈 전달 가이드」 4-1과 같음.

- fetch_observations(codes, start, end=None) -> DataFrame[code, obs_date, value]
- API 키는 환경변수 FRED_API_KEY에서만 읽음 (코드에 직접 쓰지 않음)
- FRED의 "." (결측)은 None. 0으로 바꾸지 않음
- 지표 하나라도 요청이 실패하면 예외(RuntimeError) 발생
- (code, obs_date) 중복 없이 반환

단독 실행(DB 없이 수집만 확인):
    python -m pipeline.collect --start 2026-09-01
    python -m pipeline.collect --start 2005-01-01 --out sample_observations.csv
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import time

import pandas as pd
import requests

SERIES = ["DEXKOUS", "DGS10", "SP500", "VIXCLS", "BAA10Y"]

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
TIMEOUT_SEC = 30
MAX_TRIES = 3            # 일시적 오류(네트워크·서버·호출 한도) 재시도 횟수
RETRY_WAIT_SEC = 3       # 재시도 간격(초), 시도마다 늘어남


def _api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "환경변수 FRED_API_KEY가 없습니다. "
            "터미널에서 export FRED_API_KEY=\"본인키\" 를 먼저 실행하세요."
        )
    return key


def _check_date(name: str, value: str | None) -> None:
    if value is None:
        return
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{name}는 YYYY-MM-DD 형식이어야 합니다: {value!r}") from e


def _fetch_one(code: str, start: str, end: str | None, key: str) -> list[dict]:
    """지표 1개를 FRED에서 받아 원본 observations 목록을 반환. 실패 시 예외."""
    params = {
        "series_id": code,
        "api_key": key,
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
    }
    if end:
        params["observation_end"] = end

    last_error = ""
    for attempt in range(1, MAX_TRIES + 1):
        try:
            resp = requests.get(FRED_URL, params=params, timeout=TIMEOUT_SEC)
        except requests.RequestException as e:
            last_error = f"네트워크 오류: {type(e).__name__}"
        else:
            if resp.status_code == 200:
                data = resp.json()
                if "observations" not in data:
                    raise RuntimeError(f"[{code}] FRED 응답에 observations가 없습니다.")
                return data["observations"]
            # 잘못된 요청(지표 코드 오류, 키 오류 등)은 재시도해도 같으므로 바로 중단
            if resp.status_code in (400, 401, 403, 404):
                msg = ""
                try:
                    msg = resp.json().get("error_message", "")
                except ValueError:
                    pass
                raise RuntimeError(f"[{code}] FRED 요청 실패 HTTP {resp.status_code}: {msg}")
            last_error = f"HTTP {resp.status_code}"   # 429(호출 한도), 5xx(서버 오류) → 재시도
        if attempt < MAX_TRIES:
            time.sleep(RETRY_WAIT_SEC * attempt)
    raise RuntimeError(f"[{code}] FRED 요청 {MAX_TRIES}회 실패: {last_error}")


def _to_value(raw) -> float | None:
    """FRED 값(문자열)을 숫자로. "." 이나 빈 값은 None."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text in ("", "."):
        return None
    return float(text)


def fetch_observations(codes: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    """FRED에서 지표별 일별 값을 받아 정리된 표로 반환.

    입력:
        codes: FRED 코드 목록 (예: SERIES)
        start: "YYYY-MM-DD"
        end:   "YYYY-MM-DD" 또는 None(오늘까지)
    출력 컬럼:
        code (str), obs_date (datetime.date), value (float 또는 None)
    """
    if not codes:
        raise ValueError("codes가 비어 있습니다.")
    _check_date("start", start)
    _check_date("end", end)
    key = _api_key()

    rows: list[dict] = []
    for code in codes:
        for o in _fetch_one(code, start, end, key):
            rows.append({
                "code": code,
                "obs_date": dt.date.fromisoformat(o["date"]),
                "value": _to_value(o.get("value")),
            })

    df = pd.DataFrame(rows, columns=["code", "obs_date", "value"])
    # 결측을 NaN이 아닌 None으로 유지 (계약: float 또는 None)
    df["value"] = df["value"].astype(object).where(df["value"].notna(), None)
    df = (df.drop_duplicates(subset=["code", "obs_date"], keep="last")
            .sort_values(["code", "obs_date"])
            .reset_index(drop=True))
    return df


def _main() -> None:
    p = argparse.ArgumentParser(description="FRED 수집 단독 확인 (DB 사용 안 함)")
    p.add_argument("--start", default=(dt.date.today() - dt.timedelta(days=30)).isoformat())
    p.add_argument("--end", default=None)
    p.add_argument("--codes", default=",".join(SERIES), help="쉼표로 구분, 기본 5개 지표")
    p.add_argument("--out", default=None, help="결과를 저장할 CSV 경로 (선택)")
    a = p.parse_args()

    df = fetch_observations([c.strip() for c in a.codes.split(",") if c.strip()], a.start, a.end)
    summary = df.groupby("code").agg(
        rows=("obs_date", "size"),
        first=("obs_date", "min"),
        last=("obs_date", "max"),
        missing=("value", lambda s: int(s.isna().sum())),
    )
    print(summary.to_string())
    if a.out:
        df.to_csv(a.out, index=False, encoding="utf-8-sig")
        print(f"\n저장: {a.out} ({len(df)}행)")


if __name__ == "__main__":
    _main()
