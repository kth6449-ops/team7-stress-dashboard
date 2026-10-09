# 7조 API 규격 정의서 v0.1 (C → D)

- 작성: C 파트 · 2026-10-10 전달용
- 근거: 「C·D API 연동 규격 통합 정의안」, 상세 개발·구현 가이드 v1.1
- 상태: **D 개발 착수용 계약안**. 필드명·자료형·구조는 이 문서 기준으로 고정하며, 변경 시 C가 D에게 먼저 공유함.
- `samples/` 의 모든 수치는 **가상 데이터(DEMO)** 이며 실제 금융시장 수치가 아님.

---

## 1. 공통 규칙

| 항목 | 규칙 |
|---|---|
| 기본 URL | 10/12 임시 서버 배포 후 공유 (`https://<render-주소>`) |
| 경로 접두어 | 없음 (`/api/v1` 사용하지 않음) |
| 요청 방식 | 모두 `GET` |
| 응답 형식 | `application/json`, UTF-8 |
| 날짜 | `YYYY-MM-DD` 문자열 (예: `"2026-10-07"`) |
| 시각 | UTC ISO 8601, `Z` 접미사 (예: `"2026-10-08T01:05:12Z"`). 화면에서 필요 시 KST(+9h)로 변환 |
| 시장 키 | `equity`(주식) · `fx`(외환) · `rate`(금리) · `credit`(신용) — 모든 API 공통 |
| 결측 | 값이 없으면 `null`. **0은 실제 값 0**을 의미하므로 결측과 구분 |
| 배열 응답 | 배열 이름은 `items`, 날짜 오름차순 정렬 |
| 산식 버전 | 현재 `"v0.1"`. 한 응답 안에서 서로 다른 버전을 섞지 않음 |
| 계산 책임 | **D는 점수·단계·기여도를 다시 계산하지 않음.** API가 준 값을 표시만 함 |

---

## 2. API 목록

| # | 요청 | 용도 | 샘플 파일 |
|---|---|---|---|
| 1 | `GET /scores/latest` | 메인 종합 현황·진단 | `01_scores_latest.json` |
| 2 | `GET /scores?from=YYYY-MM-DD&to=YYYY-MM-DD` | 점수 추이 차트 | `02_scores_history.json` |
| 3 | `GET /indicators` | 5개 지표 현황·변화량 표 | `03_indicators.json` |
| 4 | `GET /indicators/{code}/observations?from=&to=` | 지표 상세 차트 | `04_observations.json` |
| 5 | `GET /health` | 서버·데이터 갱신 상태 | `05_health.json` |
| 6 | `GET /methodology` | 산식 안내 (후순위, 정적 HTML 대체 가능) | `07_methodology.json` |

오류 응답 예시는 `06_errors.json`, 예외 상황 샘플은 `samples/cases/` 에 있음.

---

## 3. API별 상세

### 3-1. `GET /scores/latest`

마지막 **정상 확정** 결과 1건을 반환. 파라미터 없음.

| 필드 | 자료형 | 설명 |
|---|---|---|
| `as_of_date` | string(date) | 점수 기준일 (5개 지표가 모두 있는 마지막 공통 날짜) |
| `rule_version` | string | 산식 버전 |
| `total_score` | number | 종합점수 0~100 |
| `total_percentile` | number \| null | 종합점수의 과거 분포 백분위 0~100 |
| `stage` | string | `"정상"` · `"주의"` · `"경계"` · `"위험"` |
| `markets` | object | `equity`·`fx`·`rate`·`credit` 각 0~25 |
| `contributions` | object | 시장별 기여율(%). 종합점수가 0이면 **모든 값 `null`** |
| `spread_count` | integer | 12.5점 이상인 시장 수 0~4 |
| `is_provisional` | boolean | 잠정치 여부. 1차 구현은 항상 `false` |
| `computed_at` | string(datetime) | 계산 완료 시각(UTC) |

- 데이터가 하나도 없으면 **404**.
- 예외 샘플: `cases/01_scores_latest_total_zero.json` (종합 0점 → 기여도 `null`)

### 3-2. `GET /scores?from=&to=`

| 파라미터 | 필수 | 설명 |
|---|---|---|
| `from` | 필수 | 시작일 (포함) |
| `to` | 필수 | 종료일 (포함) |

응답: `from`, `to`, `rule_version`, `items[]`

`items[]` 각 원소: `as_of_date`, `total_score`, `markets{equity, fx, rate, credit}`

- 계산 결과가 없는 날짜는 **배열에서 빠짐**. 0점을 만들거나 보간하지 않음.
  - 샘플에서는 `2026-10-01`이 빠져 있음 (결측일 사례)
- 기간 안에 결과가 없으면 **200 + `items: []`** (`cases/02_scores_history_empty.json`)
- `from > to` 또는 날짜 형식 오류 → **422**

### 3-3. `GET /indicators`

응답: `items[]` (5개 지표), `updated_at`

| 필드 | 자료형 | 설명 |
|---|---|---|
| `code` | string | FRED 코드: `DEXKOUS`, `DGS10`, `SP500`, `VIXCLS`, `BAA10Y` |
| `name` | string | 한글 지표명 |
| `market` | string | 시장 키 |
| `unit` | string | 값 단위: `KRW/USD`, `%`, `index`, `%p` |
| `obs_date` | string(date) | **이 지표의** 최신 관측일 (지표마다 다를 수 있음) |
| `value` | number \| null | 최신 값 |
| `changes.d1` | number \| null | 직전 관측치 대비 변화 |
| `changes.m1` | number \| null | 21개 관측치 전 대비 변화 |
| `changes.m3` | number \| null | 63개 관측치 전 대비 변화 |
| `change_unit` | string | 변화 단위: 환율·S&P500 `%`, 금리·신용 `%p`, VIX `pt` |
| `source_url` | string | FRED 출처 페이지 |

- 과거 관측치가 부족하면 해당 변화량만 `null` (샘플: DEXKOUS의 `m3`)
- `obs_date`는 점수 기준일 `as_of_date`와 다를 수 있음. 화면에서 두 날짜를 구분해 표시 권장.

### 3-4. `GET /indicators/{code}/observations?from=&to=`

응답: `code`, `unit`, `items[]` — 각 원소 `obs_date`, `value`

- 휴장 등으로 원본이 비어 있는 날은 `value: null`로 **포함됨** (샘플: `2026-10-01`)
- 없는 지표 코드 → **404**

### 3-5. `GET /health`

| 필드 | 설명 |
|---|---|
| `status` | 서버 응답 가능 여부. 응답이 오면 항상 `"ok"` |
| `data_status` | `"fresh"` 정상 · `"stale"` 갱신 지연 · `"empty"` 데이터 없음 |
| `latest_as_of_date` | 최신 점수 기준일 (`empty`면 `null`) |
| `last_success_at` | 마지막 정상 실행 시각 (`empty`면 `null`) |

- `stale` 판정 기준(현재 제안): 한국 날짜와 `latest_as_of_date` 차이가 4일 초과. **실제 데이터 지연 확인 후 조정 예정** (아래 미결 사항 참조).
- 예외 샘플: `cases/05_health_stale.json`, `cases/05_health_empty.json`

### 3-6. `GET /methodology` (후순위)

`rule_version`, `indicators[]`, `market_weights`, `percentile_window_years`, `risk_stage_thresholds`, `spread_threshold`.
구현 부담이 크면 D가 정적 안내 화면으로 대체해도 됨.

---

## 4. 오류 응답

| 상황 | HTTP | 본문 |
|---|---|---|
| 정상 | 200 | 위 JSON |
| 최신 점수 없음 / 없는 지표 코드 | 404 | `{"detail": "문자열"}` |
| 파라미터 오류 | 422 | `{"detail": [ {...}, ... ]}` **또는** `{"detail": "문자열"}` |
| 서버·DB 오류 | 500 | `{"detail": "서버 처리 중 오류가 발생했습니다."}` |

- **D는 `detail`이 문자열·배열 두 형태 모두 올 수 있다고 가정하고 처리.**
- 응답에 DB 주소·비밀번호·내부 오류 내용은 노출하지 않음.

---

## 5. 샘플 데이터 일관성 (검증 완료)

`gen_samples.py`로 아래 규칙을 자동 검증함.

- 최신점수: 시장점수 합 = 종합점수(68), 기여도 합 ≈ 100%, 백분위 92 → `경계`, 12.5점 이상 시장 3개
- 추이: 9개 날짜, 오름차순, 날짜별 시장점수 합 = 종합점수, 마지막 날 = 최신점수
- 지표: 5개 전체, `null` 사례 포함

---

## 6. 미결 사항 (A·B·C 협의 필요 — D 개발에는 영향 없음)

| # | 항목 | 현재 상태 | 영향 |
|---|---|---|---|
| 1 | 10년 백분위와 데이터 수집 기간 | B와 협의 필요 | 실제 추이 차트의 시작일, `total_percentile`이 `null`일 수 있음 → **D는 `null` 표시 처리 필요** |
| 2 | `stale` 판정 기준(4일) | 원/달러 공개 지연 실측 후 조정 | `/health`의 `data_status` 값 |
| 3 | `compute_scores()` 출력 컬럼 | B·C 협의 | API 필드 값의 출처 (필드명은 불변) |

필드명·구조는 위 미결 사항과 관계없이 **고정**함.
