"""7조 금융시장 스트레스 점수 계산 모듈 (B 담당).

원천데이터(code, obs_date, value)를 받아 아래 순서로 계산한다.
    ① 지표별 정리 → ② 스트레스 변환값 → ③ 과거 대비 백분위 → ④ 지표 점수(0~25)
    → ⑤ 시장점수 4개 → ⑥ 공통 기준일 → ⑦ 종합점수(0~100) → ⑧ 종합 백분위
    → ⑨ 위험단계 → ⑩ 동시 스트레스 시장 수

산식 출처: 「1. 대시보드 개발 기획안 현행화 버전」 3·4장, 「3. 개발 가이드」 3장.
연결 규격: C 「시스템운영_모듈전달_가이드 v1.0」 5장 (함수 이름·출력 컬럼).
데이터 기준: B 「데이터기준_회신 v1.0」 (결정 1-A, 2-A, 추가 확인 #5·#6).

이 모듈은 순수 계산만 한다. DB 접속·FRED 호출·파일 저장을 하지 않으며,
같은 입력에는 항상 같은 결과를 돌려준다 (C의 run.py가 매일 전체 기간을 재계산하기 때문).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RULE_VERSION = "v0.1"

# 데이터 기준 결정 결과는 여기에만 반영한다. 코드 본문에는 숫자 기준을 직접 쓰지 않는다.
CONFIG = {
    # --- C 계약 키 (이름 변경 금지) ---
    "window_years_max": 10,  # 백분위 비교 최대 기간, 달력 기준 (결정 1-A)
    "window_years_min": 2,  # 첫 유효 값이 평가일보다 이만큼 앞서야 계산 (결정 1-A)
    "stage_thresholds": {"주의": 75, "경계": 90, "위험": 95},
    "spread_threshold": 12.5,
    # --- B 추가 키 (기획안 산식의 기존 값을 옮긴 것) ---
    "change_lag_obs": 21,  # 환율 상승률·금리 변화폭의 비교 시점 (실제 관측값 개수)
    "drawdown_window_obs": 252,  # S&P500 최고치 계산 구간 (평가일 포함 관측값 개수)
}

SERIES = ["DEXKOUS", "DGS10", "SP500", "VIXCLS", "BAA10Y"]

# 시장 ↔ 원천지표 연결. 주식시장은 두 지표 점수의 단순 평균 (기획안 3-3).
MARKETS = {
    "equity": ["SP500", "VIXCLS"],
    "fx": ["DEXKOUS"],
    "rate": ["DGS10"],
    "credit": ["BAA10Y"],
}

INDICATOR_COLUMNS = ["code", "as_of_date", "rule_version", "stress_value", "percentile", "score"]
DAILY_COLUMNS = [
    "as_of_date",
    "rule_version",
    "equity_score",
    "fx_score",
    "rate_score",
    "credit_score",
    "total_score",
    "total_percentile",
    "stage",
    "spread_count",
    "is_provisional",
]

# 부동소수점 오차로 "같은 값"이 다르게 판정되는 것을 막는 허용 오차.
# 예: 4.23 − 4.09 와 4.33 − 4.19 는 둘 다 0.14지만 컴퓨터에서는 끝자리가 다를 수 있다.
_TIE_TOLERANCE = 1e-12


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------


def compute_scores(observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """원천데이터로 지표별 점수와 날짜별 종합 결과를 계산한다.

    Args:
        observations: load_observations()가 반환한 전체 원본.
            컬럼 code(str), obs_date(date), value(float/NaN). 5개 지표 모두 포함해야 한다.

    Returns:
        (indicator_scores, daily_scores)
        - indicator_scores: INDICATOR_COLUMNS. 변환값이 있는 날짜마다 한 행.
          비교 기간이 부족하면 percentile·score는 NaN (회신 #6).
        - daily_scores: DAILY_COLUMNS. 5개 지표 점수가 모두 있는 날짜만 (결정 2-A).
          종합 비교 기간이 부족하면 total_percentile NaN, stage None (회신 #6).
        값은 반올림하지 않는다 (회신 #5). computed_at·run_id는 C가 저장 시 채운다.

    Raises:
        ValueError: 필수 컬럼·지표가 없거나, 같은 (code, obs_date)가 중복되거나, CONFIG가 잘못된 경우.
    """
    _validate_config(CONFIG)
    prepared = _prepare(observations)

    indicator_frames = []
    for code in SERIES:
        series = prepared.loc[prepared["code"] == code].set_index("obs_date")["value"]
        # 0으로 나누기 등으로 생긴 ±inf는 '계산 불가'로 보고 NaN으로 바꾼 뒤 제외한다.
        # (inf를 남기면 허용 오차 비교가 깨져 0점으로 저장되는 문제가 있었다 — 10/10 검토)
        stress = _stress_values(code, series).replace([np.inf, -np.inf], np.nan).dropna()
        percentile = _rolling_percentile(stress)
        indicator_frames.append(
            pd.DataFrame(
                {
                    "code": code,
                    "as_of_date": stress.index,
                    "rule_version": RULE_VERSION,
                    "stress_value": stress.to_numpy(),
                    "percentile": percentile.to_numpy(),
                    "score": _to_score(percentile).to_numpy(),
                }
            )
        )
    indicator_scores = pd.concat(indicator_frames, ignore_index=True)

    daily_scores = _daily_scores(indicator_scores)

    return _finalize_indicator(indicator_scores), _finalize_daily(daily_scores)


# ---------------------------------------------------------------------------
# ① 정리
# ---------------------------------------------------------------------------


def _prepare(observations: pd.DataFrame) -> pd.DataFrame:
    """입력을 검사하고 계산하기 좋은 형태로 정리한다.

    - 필수 컬럼·지표가 없으면 오류를 낸다. 일부 지표 없이 조용히 계산하면
      화면에 틀린 종합점수가 나가기 때문이다.
    - value가 NaN인 행은 제거한다. 0으로 바꾸지 않는다.
      → "21거래일 전"이 달력 날짜가 아니라 실제 관측값 21개 전이 된다 (개발 가이드 3-3).
    - DB의 numeric 컬럼은 Decimal로 들어올 수 있으므로 float로 바꾼다.
    - 값이 하나도 없는(전부 NaN) 지표도 '지표 없음'과 같게 보고 오류를 낸다.
      그대로 두면 오류 없이 daily_scores가 0행이 되어 '성공·0건'으로 기록될 수 있다.
    - 무한대(inf) 값은 정상 금융 데이터가 아니므로 오류를 낸다.
    """
    required = {"code", "obs_date", "value"}
    missing_cols = required - set(observations.columns)
    if missing_cols:
        raise ValueError(f"입력에 필요한 컬럼이 없습니다: {sorted(missing_cols)}")

    df = observations.loc[:, ["code", "obs_date", "value"]].copy()
    df["code"] = df["code"].astype(str)
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    df["value"] = pd.to_numeric(df["value"]).astype(float)
    df = df.loc[df["code"].isin(SERIES)]  # 계산에 쓰지 않는 코드는 무시

    if np.isinf(df["value"]).any():
        sample = df.loc[np.isinf(df["value"]), ["code", "obs_date"]].head(3).to_dict("records")
        raise ValueError(f"무한대(inf) 값이 있습니다. 예: {sample}")

    duplicated = df.duplicated(subset=["code", "obs_date"], keep=False)
    if duplicated.any():
        sample = df.loc[duplicated, ["code", "obs_date"]].head(3).to_dict("records")
        raise ValueError(f"같은 (code, obs_date)가 중복됩니다. 예: {sample}")

    df = df.loc[df["value"].notna()]
    missing_codes = set(SERIES) - set(df["code"].unique())
    if missing_codes:
        raise ValueError(f"입력에 필요한 지표가 없거나 값이 모두 비어 있습니다: {sorted(missing_codes)}")

    return df.sort_values(["code", "obs_date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# ② 스트레스 변환값
# ---------------------------------------------------------------------------


def _stress_values(code: str, values: pd.Series) -> pd.Series:
    """지표 값을 "불안할수록 큰 값"으로 바꾼다 (기획안 3-1).

    values는 결측이 제거되고 날짜순으로 정렬된 한 지표의 시계열이다.
    shift·rolling은 행(=실제 관측값) 단위로 움직이므로 휴장일은 자동으로 건너뛴다.
    준비 기간(21개·252개)이 안 되는 앞부분은 NaN이 된다.
    """
    lag = CONFIG["change_lag_obs"]
    window = CONFIG["drawdown_window_obs"]

    if code == "DEXKOUS":
        # 1개월 환율 상승률. 원화 약세일수록 커진다.
        return values / values.shift(lag) - 1
    if code == "DGS10":
        # 1개월 금리 변화폭. 오르든 내리든 크게 움직일수록 커진다.
        return (values - values.shift(lag)).abs()
    if code == "SP500":
        # 최근 1년(평가일 포함 252개) 최고치 대비 낙폭.
        peak = values.rolling(window, min_periods=window).max()
        return 1 - values / peak
    if code in ("VIXCLS", "BAA10Y"):
        # 수준 자체가 스트레스. 변환하지 않는다.
        return values.copy()
    raise ValueError(f"알 수 없는 지표 코드: {code}")


# ---------------------------------------------------------------------------
# ③ 백분위  (지표 백분위와 종합 백분위가 같은 함수를 쓴다)
# ---------------------------------------------------------------------------


def _rolling_percentile(series: pd.Series) -> pd.Series:
    """각 날짜의 값이 그날까지의 과거 분포에서 몇 % 위치인지 구한다 (결정 1-A).

    규칙:
    - 비교 구간: 달력상 (t − window_years_max년, t]. 평가일 당일 값 포함.
      관측값 개수가 아니라 달력으로 세는 이유: 지표마다 휴장·결측일이 달라서
      개수로 세면 지표별 실제 비교 기간이 달라진다.
    - 최소 기간: 시계열의 첫 유효 날짜가 t − window_years_min년 이전이어야 계산.
      미달이면 NaN (0과 구분).
    - 미래 데이터 없음: t 이후 값은 비교 구간에 절대 들어가지 않는다.
    - 중간순위: P = 100 × (작은 값 수 + 0.5 × 같은 값 수) / 전체 수.
      같은 값이 반복되는 시계열이 P=100(만점)으로 부풀려지는 것을 막는다.

    Args:
        series: 날짜(DatetimeIndex, 오름차순) → 값. NaN은 미리 제거되어 있어야 한다.
    """
    if series.empty:
        return pd.Series(dtype=float, index=series.index)

    dates = pd.DatetimeIndex(series.index)
    values = series.to_numpy(dtype=float)

    window_start = dates - pd.DateOffset(years=CONFIG["window_years_max"])
    earliest_needed = dates - pd.DateOffset(years=CONFIG["window_years_min"])
    first_date = dates[0]

    # 비교 구간 시작 위치: window_start보다 '큰' 첫 날짜 → (t − 10년, t] 의 왼쪽 열린 구간
    lo = dates.searchsorted(window_start, side="right")

    result = np.full(len(values), np.nan)
    for i, x in enumerate(values):
        if first_date > earliest_needed[i]:
            continue  # 쌓인 과거가 최소 기간보다 짧음 → 계산하지 않음
        window = values[lo[i] : i + 1]  # i+1: 평가일 당일 포함, 이후 값은 제외
        tol = _TIE_TOLERANCE * max(1.0, abs(x))
        less = np.count_nonzero(window < x - tol)
        equal = np.count_nonzero(np.abs(window - x) <= tol)
        result[i] = 100.0 * (less + 0.5 * equal) / len(window)

    return pd.Series(result, index=series.index)


# ---------------------------------------------------------------------------
# ④ 지표 점수
# ---------------------------------------------------------------------------


def _to_score(percentile: pd.Series) -> pd.Series:
    """백분위를 0~25점으로 바꾼다: 25 × max(0, (P − 50) / 50) (기획안 3-2).

    과거 분포의 중간(50) 이하인 평범한 움직임은 0점, 상위 절반부터 점수가 오른다.
    P가 NaN이면 점수도 NaN으로 남긴다.
    """
    return 25.0 * ((percentile - 50.0) / 50.0).clip(lower=0.0)


# ---------------------------------------------------------------------------
# ⑤~⑩ 날짜별 종합 결과
# ---------------------------------------------------------------------------


def _daily_scores(indicator_scores: pd.DataFrame) -> pd.DataFrame:
    """지표 점수로 시장점수·종합점수·종합 백분위·위험단계·확산 수를 계산한다."""
    wide = indicator_scores.pivot(index="as_of_date", columns="code", values="score")

    # ⑥ 공통 기준일: 5개 지표 점수가 모두 있는 날짜만 남긴다 (결정 2-A).
    #    서로 다른 날짜의 값을 섞어 합산하지 않기 위해서다.
    wide = wide.reindex(columns=SERIES).dropna(how="any").sort_index()

    daily = pd.DataFrame(index=wide.index)
    for market, codes in MARKETS.items():
        # ⑤ 시장점수. 주식은 S&P500·VIX 평균이라 최대 25점을 넘지 않는다.
        daily[f"{market}_score"] = wide[codes].mean(axis=1)

    market_cols = [f"{m}_score" for m in MARKETS]
    daily["total_score"] = daily[market_cols].sum(axis=1)  # ⑦ 0~100

    # ⑧ 종합 백분위: 지표 백분위와 같은 규칙(최소 2년·최대 10년·중간순위)
    daily["total_percentile"] = _rolling_percentile(daily["total_score"])

    daily["stage"] = daily["total_percentile"].map(_stage)  # ⑨
    daily["spread_count"] = (  # ⑩ 12.5점 = 과거 상위 25%(P=75)에 해당하는 시장점수
        daily[market_cols].ge(CONFIG["spread_threshold"]).sum(axis=1).astype(int)
    )
    daily["rule_version"] = RULE_VERSION
    daily["is_provisional"] = False  # 2-A에서는 잠정치를 만들지 않는다

    return daily.rename_axis("as_of_date").reset_index()


def _stage(total_percentile: float) -> str | None:
    """종합 백분위로 위험단계를 정한다 (기획안 4-1).

    75 미만 정상 / 75 이상 90 미만 주의 / 90 이상 95 미만 경계 / 95 이상 위험.
    종합점수 68점이 68백분위를 뜻하지 않으므로 반드시 백분위로 판정한다.
    백분위가 없으면 단계도 판정하지 않는다(None).
    """
    if pd.isna(total_percentile):
        return None
    stage = "정상"
    for name, threshold in sorted(CONFIG["stage_thresholds"].items(), key=lambda kv: kv[1]):
        if total_percentile >= threshold:
            stage = name
    return stage


# ---------------------------------------------------------------------------
# 출력 정리·검사
# ---------------------------------------------------------------------------


def _finalize_indicator(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼 순서·자료형을 C 계약 5-2와 같게 맞춘다."""
    out = df.sort_values(["code", "as_of_date"]).reset_index(drop=True)
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).dt.date
    return out.loc[:, INDICATOR_COLUMNS]


def _finalize_daily(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼 순서·자료형을 C 계약 5-3과 같게 맞춘다."""
    out = df.sort_values("as_of_date").reset_index(drop=True)
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).dt.date
    out["stage"] = out["stage"].astype(object).where(out["stage"].notna(), None)
    out["is_provisional"] = out["is_provisional"].astype(bool)
    return out.loc[:, DAILY_COLUMNS]


def _validate_config(config: dict) -> None:
    """CONFIG 값이 서로 모순되지 않는지 확인한다. 잘못된 설정으로 조용히 계산하지 않기 위해서다."""
    required = {"window_years_max", "window_years_min", "stage_thresholds",
                "spread_threshold", "change_lag_obs", "drawdown_window_obs"}
    missing = required - set(config)
    if missing:
        raise ValueError(f"CONFIG: 필요한 키가 없습니다: {sorted(missing)}")
    if not 0 < config["window_years_min"] <= config["window_years_max"]:
        raise ValueError("CONFIG: 0 < window_years_min <= window_years_max 이어야 합니다.")
    thresholds = list(config["stage_thresholds"].values())
    # 단계 판정(_stage)은 값 크기순으로 정렬해 쓰므로, 입력 순서가 아니라 값만 검사한다.
    if len(set(thresholds)) != len(thresholds) or not all(0 <= t <= 100 for t in thresholds):
        raise ValueError("CONFIG: stage_thresholds는 0~100 사이의 서로 다른 값이어야 합니다.")
    if not 0 < config["spread_threshold"] <= 25:
        raise ValueError("CONFIG: spread_threshold는 0 초과 25 이하여야 합니다 (시장점수 범위).")
    if config["change_lag_obs"] < 1 or config["drawdown_window_obs"] < 1:
        raise ValueError("CONFIG: change_lag_obs, drawdown_window_obs는 1 이상이어야 합니다.")
