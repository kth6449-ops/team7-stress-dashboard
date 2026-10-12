# Team 7 · 금융시장 스트레스 모니터링 대시보드

KAIST MBA 클라우드컴퓨팅실습 7조 팀 프로젝트.
FRED 5개 지표를 매일 수집해 4개 시장의 스트레스 점수를 계산하고, API와 웹 화면으로 제공한다.

```
FRED API → pipeline(GitHub Actions) → Supabase(PostgreSQL) → api(FastAPI·Render) → frontend(Vercel)
```

## 폴더와 담당

| 경로 | 내용 | 담당 |
|---|---|---|
| `pipeline/collect.py`, `pipeline/db.py`, `db/schema.sql` | 수집·DB | A |
| `pipeline/scoring.py`, `tests/` (`tests/data/` 검증용 데이터) | 점수 계산 | B |
| `pipeline/run.py`, `api/`, `.github/workflows/` | 통합·API·자동화 | C |
| `frontend/` | 화면 | D |
| `docs/api/` | API 규격·샘플 | C |
| `docs/modules/` | A·B 전달본 설명서 (버전별 보관) | A·B |

## 운영 규칙

- `main`은 통합 테스트를 통과한 코드만. 합치기는 C만 수행.
- A·B는 ZIP으로 전달 → C가 `integ/*` 브랜치에서 테스트 후 반영.
- D는 `feature/frontend` 브랜치에서 작업 후 Pull Request.
- **API 키·DB 비밀번호는 절대 커밋하지 않음.** 환경변수로만 사용.

## 로컬 실행 (C)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 임시 API (샘플 JSON 반환)
uvicorn api.main:app --reload        # http://127.0.0.1:8000/docs

# 점수 계산 테스트 (pytest는 테스트할 때만 설치)
pip install pytest && pytest tests/test_scoring.py -q

# 파이프라인 (A·B 모듈 반영 후)
export FRED_API_KEY=...  DATABASE_URL=...
python -m pipeline.run --start 2005-01-01   # 최초 1회: 전체 적재 (백분위에 최소 2년 필요)
python -m pipeline.run --days 14            # 이후 매일
```

## 필요한 환경변수

| 이름 | 사용처 |
|---|---|
| `FRED_API_KEY` | GitHub Actions, 로컬 |
| `DATABASE_URL` | GitHub Actions, Render, 로컬 |
| `ALLOWED_ORIGINS` | Render (화면 주소, 쉼표 구분) |
