"""[A 담당] FRED 데이터 수집.

함수 이름·입출력은 「시스템 운영·모듈 전달 가이드」 4-1과 같아야 함.
이 파일은 계약을 보여주는 뼈대이며, A의 전달본으로 교체됨.
"""
import pandas as pd

SERIES = ["DEXKOUS", "DGS10", "SP500", "VIXCLS", "BAA10Y"]


def fetch_observations(codes: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    """FRED에서 지표별 일별 값을 받아 정리된 표로 반환.

    입력:
        codes: FRED 코드 목록 (예: SERIES)
        start: "YYYY-MM-DD"
        end:   "YYYY-MM-DD" 또는 None(오늘까지)
    출력 컬럼:
        code (str), obs_date (date), value (float 또는 None)
    규칙:
        - FRED의 "." (결측)은 None. 0으로 바꾸지 않음
        - API 키는 환경변수 FRED_API_KEY에서 읽음
        - 지표 하나라도 요청 실패 시 예외 발생
    """
    raise NotImplementedError("A 전달본으로 교체 예정")
