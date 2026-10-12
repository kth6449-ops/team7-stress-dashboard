"""scoring.py 검증 테스트.

실행: pytest tests/test_scoring.py -v

구성
- C 필수 4개 (모듈 전달 가이드 5-5): 시장점수 합 = 종합점수, 주식 = 두 지표 평균,
  결측 입력 시 0이 아닌 NaN, 백분위-단계 일치
- B 추가 검증: 점수 변환표, 21관측 전 기준, 미래 데이터 미사용, 상수 시계열,
  최소 비교 기간, 값 범위, 재현성, 출력 컬럼, 입력 오류 처리
- 실데이터 샘플(tests/data/sample_observations.csv)로 같은 규칙이 성립하는지 확인

가상 데이터는 고정 seed로 만들어 매번 같은 결과가 나온다.
엑셀 독립 계산 대조값은 10/15에 추가 예정 (B 계획 가이드 10/15).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import scoring  # noqa: E402
from pipeline.scoring import (  # noqa: E402
    DAILY_COLUMNS,
    INDICATOR_COLUMNS,
    SERIES,
    _rolling_percentile,
    _stage,
    _to_score,
    compute_scores,
)

SAMPLE_PATH = ROOT / "tests" / "data" / "sample_observations.csv"


# ---------------------------------------------------------------------------
# 테스트용 데이터
# ---------------------------------------------------------------------------


def make_observations(years: float = 5.5, seed: int = 7) -> pd.DataFrame:
    """5개 지표의 가상 일별 데이터를 만든다 (평일만, 고정 seed).

    최소 비교 기간 2년 + S&P500 준비 1년 + 종합 백분위 2년이 모두 지나도록 5.5년치를 만든다.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=int(252 * years))
    n = len(dates)
    paths = {
        "DEXKOUS": 1200 * np.exp(np.cumsum(rng.normal(0, 0.004, n))),
        "DGS10": 2.5 + np.cumsum(rng.normal(0, 0.03, n)),
        "SP500": 3000 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n))),
        "VIXCLS": 15 + 5 * np.abs(np.sin(np.arange(n) / 40)) + rng.normal(0, 1, n),
        "BAA10Y": 2.0 + 0.5 * np.sin(np.arange(n) / 90) + rng.normal(0, 0.05, n),
    }
    frames = [pd.DataFrame({"code": c, "obs_date": dates.date, "value": v}) for c, v in paths.items()]
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def synthetic():
    obs = make_observations()
    ind, daily = compute_scores(obs)
    return obs, ind, daily


@pytest.fixture(scope="module")
def sample():
    obs = pd.read_csv(SAMPLE_PATH)
    ind, daily = compute_scores(obs)
    return obs, ind, daily


# ---------------------------------------------------------------------------
# C 필수 1~4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("data", ["synthetic", "sample"])
def test_c1_market_scores_sum_to_total(data, request):
    """★C 필수 1: 시장점수 4개의 합 = 종합점수 (반올림하지 않으므로 오차 없이 일치)."""
    _, _, daily = request.getfixturevalue(data)
    assert not daily.empty
    markets = daily[["equity_score", "fx_score", "rate_score", "credit_score"]].sum(axis=1)
    np.testing.assert_allclose(markets, daily["total_score"], rtol=0, atol=1e-9)


@pytest.mark.parametrize("data", ["synthetic", "sample"])
def test_c2_equity_is_mean_of_sp500_and_vix(data, request):
    """★C 필수 2: 주식시장 점수 = (S&P500 점수 + VIX 점수) / 2."""
    _, ind, daily = request.getfixturevalue(data)
    wide = ind.pivot(index="as_of_date", columns="code", values="score")
    expected = (wide["SP500"] + wide["VIXCLS"]) / 2
    actual = daily.set_index("as_of_date")["equity_score"]
    np.testing.assert_allclose(actual, expected.loc[actual.index], atol=1e-12)


def test_c3_missing_input_is_nan_not_zero():
    """★C 필수 3: 결측 입력은 0이 아니라 NaN으로 남는다.

    - 원본 NaN은 0으로 바뀌어 계산되지 않는다 (그 날짜는 해당 지표 결과 행이 없음)
    - 그 날짜는 공통 기준일이 아니므로 종합점수 행도 없다 (0점 행이 생기지 않음)
    - 비교 기간이 부족한 앞부분은 점수가 0이 아니라 NaN
    """
    obs = make_observations()
    target = obs.loc[obs["code"] == "VIXCLS", "obs_date"].iloc[-10]
    obs.loc[(obs["code"] == "VIXCLS") & (obs["obs_date"] == target), "value"] = np.nan

    ind, daily = compute_scores(obs)

    vix_dates = set(ind.loc[ind["code"] == "VIXCLS", "as_of_date"])
    assert target not in vix_dates
    assert target not in set(daily["as_of_date"])

    early = ind[ind["percentile"].isna()]
    assert not early.empty
    assert early["score"].isna().all()  # 계산 불가 구간 점수는 NaN
    assert not (early["score"] == 0).any()


@pytest.mark.parametrize(
    "p, expected",
    [(0, "정상"), (74.99, "정상"), (75, "주의"), (89.99, "주의"), (90, "경계"),
     (94.99, "경계"), (95, "위험"), (100, "위험"), (np.nan, None)],
)
def test_c4_stage_matches_percentile_boundaries(p, expected):
    """★C 필수 4: 백분위-단계 일치 (75 이상 주의, 90 이상 경계, 95 이상 위험, NaN → None)."""
    assert _stage(p) == expected


@pytest.mark.parametrize("data", ["synthetic", "sample"])
def test_c4_stage_column_consistent(data, request):
    """★C 필수 4 (결과 표): stage 열이 total_percentile 열과 항상 일치."""
    _, _, daily = request.getfixturevalue(data)
    assert daily["stage"].tolist() == [_stage(p) for p in daily["total_percentile"]]


# ---------------------------------------------------------------------------
# B 추가 검증
# ---------------------------------------------------------------------------


def test_percentile_to_score_table():
    """기획안 3-2 변환표: P 50→0, 60→5, 75→12.5, 90→20, 95→22.5, 100→25, 50 이하 0, NaN 유지."""
    p = pd.Series([50, 60, 75, 90, 95, 100, 30, np.nan])
    expected = [0, 5, 12.5, 20, 22.5, 25, 0, np.nan]
    np.testing.assert_allclose(_to_score(p), expected)


@pytest.mark.parametrize("code", ["DEXKOUS", "DGS10"])
def test_lag_uses_actual_observations_not_calendar(code):
    """21거래일 전 = 결측을 뺀 실제 관측값 21개 전 (개발 가이드 3-3).

    DEXKOUS: 오늘 / 21관측 전 − 1,  DGS10: |오늘 − 21관측 전|
    """
    obs = make_observations()
    one = obs[obs["code"] == code].reset_index(drop=True)
    holes = one.loc[100:109, "obs_date"]  # 중간에 결측 10개
    obs.loc[(obs["code"] == code) & obs["obs_date"].isin(holes), "value"] = np.nan

    ind, _ = compute_scores(obs)
    valid = obs[(obs["code"] == code) & obs["value"].notna()].reset_index(drop=True)
    i = 130  # 결측 구간을 지나온 위치
    now, before = valid.loc[i, "value"], valid.loc[i - 21, "value"]
    expected = now / before - 1 if code == "DEXKOUS" else abs(now - before)
    row = ind[(ind["code"] == code) & (ind["as_of_date"] == valid.loc[i, "obs_date"])]
    assert row["stress_value"].iloc[0] == pytest.approx(expected, rel=1e-12)


def test_drawdown_includes_evaluation_day():
    """S&P500 낙폭: 평가일 포함 최근 252개 최고치 기준. 신고가인 날은 낙폭 0."""
    obs = make_observations()
    sp = obs[obs["code"] == "SP500"].reset_index(drop=True)
    i = 400
    window = sp.loc[i - 251 : i, "value"]
    expected = 1 - sp.loc[i, "value"] / window.max()
    ind, _ = compute_scores(obs)
    row = ind[(ind["code"] == "SP500") & (ind["as_of_date"] == sp.loc[i, "obs_date"])]
    assert row["stress_value"].iloc[0] == pytest.approx(expected)
    assert (ind.loc[ind["code"] == "SP500", "stress_value"] >= -1e-12).all()


def test_drawdown_window_is_exactly_252_obs():
    """S&P500 최고치 구간은 평가일 포함 정확히 252개: 251개 전 고점은 포함, 252개 전 고점은 제외."""
    def sp_with_peak(offset: int) -> float:
        obs = make_observations(years=3)
        sp = obs.index[obs["code"] == "SP500"]
        i = 600
        obs.loc[sp, "value"] = 100.0
        obs.loc[sp[i - offset], "value"] = 200.0  # 평가일로부터 offset개 전에 고점
        ind, _ = compute_scores(obs)
        day = obs.loc[sp[i], "obs_date"]
        row = ind[(ind["code"] == "SP500") & (ind["as_of_date"] == day)]
        return row["stress_value"].iloc[0]

    assert sp_with_peak(251) == pytest.approx(0.5)  # 구간 안: 1 − 100/200
    assert sp_with_peak(252) == pytest.approx(0.0)  # 구간 밖: 최고치 100


def test_no_look_ahead():
    """미래 데이터 미사용: 어떤 날짜 이후 값을 바꿔도 그 날짜까지의 결과는 그대로."""
    obs = make_observations(years=7)  # 2015~2021: cutoff 이전에 종합 백분위까지 존재
    ind_a, daily_a = compute_scores(obs)

    cutoff = pd.Timestamp("2020-09-30").date()
    changed = obs.copy()
    after = changed["obs_date"] > cutoff
    changed.loc[after, "value"] = changed.loc[after, "value"] * 1.5  # 미래를 크게 바꿈
    ind_b, daily_b = compute_scores(changed)

    # 빈 표끼리 비교해 통과하는 일이 없도록, cutoff 이전 결과가 실제로 있는지 먼저 확인
    assert (daily_a["as_of_date"] <= cutoff).sum() > 100
    assert daily_a.loc[daily_a["as_of_date"] <= cutoff, "total_percentile"].notna().any()
    assert not daily_a.equals(daily_b)  # cutoff 이후는 실제로 달라졌는지

    pd.testing.assert_frame_equal(
        daily_a[daily_a["as_of_date"] <= cutoff].reset_index(drop=True),
        daily_b[daily_b["as_of_date"] <= cutoff].reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(
        ind_a[ind_a["as_of_date"] <= cutoff].reset_index(drop=True),
        ind_b[ind_b["as_of_date"] <= cutoff].reset_index(drop=True),
    )


def test_constant_series_gives_p50_and_zero_score():
    """값이 계속 같으면 중간순위 백분위 = 50 → 점수 0 (만점으로 부풀려지지 않음)."""
    dates = pd.bdate_range("2015-01-01", periods=252 * 3)
    s = pd.Series(20.0, index=dates)
    p = _rolling_percentile(s).dropna()
    assert not p.empty
    np.testing.assert_allclose(p, 50.0)
    np.testing.assert_allclose(_to_score(p), 0.0)


def test_midrank_example():
    """중간순위 계산 예: 값 1~10 중 마지막(10) → 작은 값 9, 같은 값 1 → P = 95."""
    dates = pd.date_range("2010-01-01", periods=10, freq="365D")  # 최소 2년 조건 충족
    s = pd.Series(np.arange(1, 11, dtype=float), index=dates)
    assert _rolling_percentile(s).iloc[-1] == pytest.approx(95.0)


def test_float_noise_counts_as_tie():
    """끝자리 부동소수점 오차가 있는 값도 '같은 값'으로 센다.

    실제 DGS10 변화폭에는 0.13999999999999968, 0.14, 0.14000000000000012처럼
    같은 0.14가 끝자리만 다르게 저장된다. 이를 다른 값으로 세면 백분위가 최대 약 2 어긋난다
    (실데이터 검토에서 확인). 세 값이 모두 0.14로 같다면 마지막 값의 P = 100 × (0 + 0.5 × 3) / 3 = 50.
    """
    dates = pd.DatetimeIndex(["2010-01-04", "2012-06-01", "2013-01-07"])
    s = pd.Series([4.23 - 4.09, 0.14, 4.33 - 4.19], index=dates)
    assert len(set(s)) > 1  # 실제로 끝자리가 서로 다른지 (테스트 전제 확인)
    assert _rolling_percentile(s).iloc[-1] == pytest.approx(50.0)


def test_min_window_two_years():
    """첫 유효 값 이후 2년(달력) 미만이면 백분위 NaN, 정확히 2년이 되는 날부터 계산.

    달력 매일 데이터를 써서 '정확히 2년째 되는 날'이 데이터에 반드시 있도록 한다
    (평일만 쓰면 경계일이 주말일 때 경계 검사가 빠진다 — 10/10 검토에서 확인).
    """
    dates = pd.date_range("2015-01-01", "2018-01-31", freq="D")
    s = pd.Series(np.arange(len(dates), dtype=float), index=dates)
    p = _rolling_percentile(s)
    boundary = dates[0] + pd.DateOffset(years=scoring.CONFIG["window_years_min"])
    assert p[p.index < boundary].isna().all()
    assert p[p.index >= boundary].notna().all()
    assert boundary in p.index and pd.notna(p[boundary])  # 경계일 당일은 계산됨
    assert pd.isna(p[boundary - pd.Timedelta(days=1)])    # 하루 전은 NaN


def test_max_window_ten_years():
    """비교 구간은 달력상 직전 10년. 10년보다 오래된 값은 비교에서 빠진다."""
    dates = pd.date_range("2000-01-01", "2012-12-31", freq="W-FRI")
    values = np.where(dates < pd.Timestamp("2002-06-01"), 1000.0, 1.0)  # 오래된 큰 값
    values[-1] = 2.0
    s = pd.Series(values, index=dates)
    # 마지막 날 기준 직전 10년에는 1000이 없으므로 2.0이 최댓값 → P ≈ 100
    assert _rolling_percentile(s).iloc[-1] > 99.0


def test_window_excludes_exactly_ten_years_ago():
    """비교 구간 (t − 10년, t]: 정확히 10년 전 날짜는 빠지고, 그 다음 날은 들어간다."""
    t = pd.Timestamp("2020-06-15")
    ten_years_ago = t - pd.DateOffset(years=10)
    dates = pd.DatetimeIndex([ten_years_ago - pd.Timedelta(days=400), ten_years_ago,
                              ten_years_ago + pd.Timedelta(days=1), t])
    # 10년 전 날짜에만 오늘보다 큰 값 → 구간에서 빠지면 오늘이 최댓값
    s = pd.Series([1.0, 100.0, 2.0, 50.0], index=dates)
    # 비교 구간 = [2.0, 50.0] → 작은 값 1, 같은 값 1 → P = 100 × 1.5 / 2 = 75
    assert _rolling_percentile(s).iloc[-1] == pytest.approx(75.0)


@pytest.mark.parametrize("data", ["synthetic", "sample"])
def test_value_ranges(data, request):
    """값 범위: 지표·시장 점수 0~25, 종합 0~100, 백분위 0~100, 확산 0~4."""
    _, ind, daily = request.getfixturevalue(data)
    score = ind["score"].dropna()
    assert score.between(0, 25).all()
    assert ind["percentile"].dropna().between(0, 100).all()
    for col in ["equity_score", "fx_score", "rate_score", "credit_score"]:
        assert daily[col].between(0, 25).all()
    assert daily["total_score"].between(0, 100).all()
    assert daily["total_percentile"].dropna().between(0, 100).all()
    assert daily["spread_count"].between(0, 4).all()


@pytest.mark.parametrize("data", ["synthetic", "sample"])
def test_spread_count(data, request):
    """확산 수 = 시장점수가 12.5 이상인 시장 수."""
    _, _, daily = request.getfixturevalue(data)
    markets = daily[["equity_score", "fx_score", "rate_score", "credit_score"]]
    np.testing.assert_array_equal(daily["spread_count"], (markets >= 12.5).sum(axis=1))


def test_reproducible():
    """같은 입력 → 완전히 같은 결과 (C가 매일 전체 재계산하므로 필수)."""
    obs = make_observations()
    a = compute_scores(obs)
    b = compute_scores(obs.sample(frac=1, random_state=1))  # 행 순서를 섞어도 동일
    pd.testing.assert_frame_equal(a[0], b[0])
    pd.testing.assert_frame_equal(a[1], b[1])


def test_output_columns_and_types(synthetic):
    """출력 컬럼 이름·순서·자료형이 C 계약 5-2, 5-3과 같다. computed_at·run_id는 없다."""
    _, ind, daily = synthetic
    assert list(ind.columns) == INDICATOR_COLUMNS
    assert list(daily.columns) == DAILY_COLUMNS
    assert "computed_at" not in daily.columns and "run_id" not in daily.columns
    assert (ind["rule_version"] == scoring.RULE_VERSION).all()
    assert daily["spread_count"].dtype.kind == "i"
    assert daily["is_provisional"].dtype == bool and not daily["is_provisional"].any()
    assert all(type(d).__name__ == "date" for d in daily["as_of_date"].head())
    assert set(daily["stage"].dropna()) <= {"정상", "주의", "경계", "위험"}


def test_daily_only_on_common_dates(synthetic):
    """daily_scores 날짜 = 5개 지표 점수가 모두 있는 날짜 (결정 2-A)."""
    _, ind, daily = synthetic
    scored = ind.dropna(subset=["score"])
    counts = scored.groupby("as_of_date")["code"].nunique()
    common = set(counts[counts == len(SERIES)].index)
    assert set(daily["as_of_date"]) == common


def test_rows_kept_with_nan_before_min_window(synthetic):
    """회신 #6: 비교 기간이 부족한 기간도 행은 남기고 값만 NaN."""
    _, ind, daily = synthetic
    assert ind["percentile"].isna().any()  # 지표: 초반 행 존재, 백분위 NaN
    assert daily["total_percentile"].isna().any()  # 종합: 단계 없는 초반 행 존재
    assert daily.loc[daily["total_percentile"].isna(), "stage"].isna().all()


def test_accepts_decimal_and_string_dates():
    """DB에서 온 Decimal 값, 문자열 날짜도 처리한다."""
    obs = make_observations(years=3.5)
    obs["value"] = [Decimal(str(round(v, 6))) for v in obs["value"]]
    obs["obs_date"] = obs["obs_date"].astype(str)
    ind, daily = compute_scores(obs)
    assert not ind.empty and not daily.empty


def test_missing_indicator_raises():
    """지표가 하나라도 없으면 조용히 계산하지 않고 오류를 낸다."""
    obs = make_observations(years=3)
    with pytest.raises(ValueError, match="지표"):
        compute_scores(obs[obs["code"] != "BAA10Y"])


def test_duplicate_rows_raise():
    """같은 (code, obs_date) 중복은 오류."""
    obs = make_observations(years=3)
    with pytest.raises(ValueError, match="중복"):
        compute_scores(pd.concat([obs, obs.head(1)]))


def test_all_nan_indicator_raises():
    """값이 전부 비어 있는 지표도 '지표 없음'과 같이 오류 (0행 결과를 성공으로 넘기지 않음)."""
    obs = make_observations(years=3)
    obs.loc[obs["code"] == "BAA10Y", "value"] = np.nan
    with pytest.raises(ValueError, match="BAA10Y"):
        compute_scores(obs)


def test_inf_input_raises():
    """무한대 입력은 정상 데이터가 아니므로 오류."""
    obs = make_observations(years=3)
    obs.loc[obs.index[5], "value"] = np.inf
    with pytest.raises(ValueError, match="inf"):
        compute_scores(obs)


def test_zero_division_becomes_nan_not_zero_score():
    """21관측 전 환율이 0이면 변화율 계산 불가 → 그날 결과 행 없음 (inf·0점으로 저장하지 않음)."""
    obs = make_observations()
    fx = obs.index[obs["code"] == "DEXKOUS"]
    obs.loc[fx[800], "value"] = 0.0
    ind, _ = compute_scores(obs)
    assert np.isfinite(ind["stress_value"]).all()
    affected_day = obs.loc[fx[821], "obs_date"]  # 0이 21관측 전이 되는 날
    rows = ind[(ind["code"] == "DEXKOUS") & (ind["as_of_date"] == affected_day)]
    assert rows.empty


def test_unknown_codes_ignored():
    """계산에 쓰지 않는 지표 코드는 무시하고, 그 코드의 중복도 문제 삼지 않는다."""
    obs = make_observations(years=3)
    extra = pd.DataFrame({"code": ["XYZ", "XYZ"], "obs_date": [obs["obs_date"].iloc[0]] * 2, "value": [1.0, 2.0]})
    base = compute_scores(obs)
    with_extra = compute_scores(pd.concat([obs, extra], ignore_index=True))
    pd.testing.assert_frame_equal(base[1], with_extra[1])


@pytest.mark.parametrize(
    "patch, message",
    [({"spread_threshold": 30}, "spread_threshold"),
     ({"window_years_min": 11}, "window_years"),
     ({"stage_thresholds": {"주의": 75, "경계": 75, "위험": 95}}, "stage_thresholds")],
)
def test_invalid_config_raises(monkeypatch, patch, message):
    """CONFIG가 잘못되면 계산 전에 오류."""
    bad = {**scoring.CONFIG, **patch}
    monkeypatch.setattr(scoring, "CONFIG", bad)
    with pytest.raises(ValueError, match=message):
        compute_scores(make_observations(years=3))


def test_config_threshold_order_does_not_matter(monkeypatch):
    """stage_thresholds를 다른 순서로 넣어도 같은 결과 (단계는 값 크기순으로 판정)."""
    obs = make_observations(years=5)
    a = compute_scores(obs)[1]
    monkeypatch.setattr(scoring, "CONFIG", {**scoring.CONFIG, "stage_thresholds": {"위험": 95, "주의": 75, "경계": 90}})
    b = compute_scores(obs)[1]
    pd.testing.assert_frame_equal(a, b)


def test_missing_column_raises():
    obs = make_observations(years=3)
    with pytest.raises(ValueError, match="컬럼"):
        compute_scores(obs.drop(columns="value"))


def test_matches_independent_expected_values(sample):
    """★C 5-5: 실데이터 샘플 결과가 독립 계산 기대값(tools/make_expected.py)과 일치.

    기대값은 scoring.py를 쓰지 않고 날짜마다 직접 계산한 값이다 (반복문·날짜 필터·반올림 후 비교).
    엑셀 독립 계산(10/15)은 별도 추가 예정.
    """
    _, ind, daily = sample
    exp_ind = pd.read_csv(ROOT / "tests" / "data" / "expected_indicator_scores.csv", parse_dates=["as_of_date"])
    exp_daily = pd.read_csv(ROOT / "tests" / "data" / "expected_daily_scores.csv", parse_dates=["as_of_date"])

    got_ind = ind.assign(as_of_date=pd.to_datetime(ind["as_of_date"])).sort_values(["code", "as_of_date"])
    exp_ind = exp_ind.sort_values(["code", "as_of_date"])
    assert len(got_ind) == len(exp_ind)
    assert (got_ind["code"].to_numpy() == exp_ind["code"].to_numpy()).all()
    assert (got_ind["as_of_date"].to_numpy() == exp_ind["as_of_date"].to_numpy()).all()
    for col in ["stress_value", "percentile", "score"]:
        np.testing.assert_allclose(got_ind[col], exp_ind[col], rtol=0, atol=1e-9, equal_nan=True, err_msg=col)

    got_daily = daily.assign(as_of_date=pd.to_datetime(daily["as_of_date"]))
    assert (got_daily["as_of_date"].to_numpy() == exp_daily["as_of_date"].to_numpy()).all()
    for col in ["equity_score", "fx_score", "rate_score", "credit_score", "total_score", "total_percentile"]:
        np.testing.assert_allclose(got_daily[col], exp_daily[col], rtol=0, atol=1e-9, equal_nan=True, err_msg=col)
    assert got_daily["stage"].tolist() == [None if pd.isna(v) else v for v in exp_daily["stage"]]
    assert (got_daily["spread_count"].to_numpy() == exp_daily["spread_count"].to_numpy()).all()


def test_sample_starts_where_expected(sample):
    """실데이터 샘플(2016-10~2021-12): 종합점수는 약 2019-10, 위험단계는 약 2021-10부터."""
    _, _, daily = sample
    first_total = pd.Timestamp(daily["as_of_date"].min())
    first_stage = pd.Timestamp(daily.loc[daily["stage"].notna(), "as_of_date"].min())
    assert pd.Timestamp("2019-09-01") <= first_total <= pd.Timestamp("2019-11-30")
    assert pd.Timestamp("2021-09-01") <= first_stage <= pd.Timestamp("2021-11-30")
