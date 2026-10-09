"""[B 담당] 스트레스 점수 계산.

함수 이름·입출력은 「시스템 운영·모듈 전달 가이드」 5장과 같아야 함.
이 파일은 계약을 보여주는 뼈대이며, B의 전달본으로 교체됨.
"""
import pandas as pd

RULE_VERSION = "v0.1"

# 데이터 기준 결정(의사결정 요청서) 결과는 여기에만 반영. 아래 값은 예시.
CONFIG = {
    "window_years_max": 10,
    "window_years_min": 2,
    "stage_thresholds": {"주의": 75, "경계": 90, "위험": 95},
    "spread_threshold": 12.5,
}


def compute_scores(observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """입력: code, obs_date, value (전체 원본)

    출력 1 indicator_scores:
        code, as_of_date, rule_version, stress_value, percentile, score
    출력 2 daily_scores:
        as_of_date, rule_version, equity_score, fx_score, rate_score, credit_score,
        total_score, total_percentile, stage, spread_count, is_provisional

    규칙: DB·FRED 접근 금지(순수 계산), 같은 입력이면 같은 결과,
          미래 데이터 사용 금지, 계산 불가는 0이 아닌 NaN/None.
    """
    raise NotImplementedError("B 전달본으로 교체 예정")
