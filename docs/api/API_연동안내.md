# API 연동 안내 (D 담당용)

## 1. 단계별 연결 방식

| 시점 | 데이터 출처 | D가 할 일 |
|---|---|---|
| 10/10 ~ | `samples/` 의 JSON 파일 | 화면·차트·해석 문구 개발 |
| 10/12 ~ | C의 임시 API (고정 JSON 반환) | 주소만 바꿔 실제 HTTP 호출 확인 |
| 10/14 ~ | C의 실제 API (DB 조회) | 코드 수정 없이 실제 값 표시 확인 |

샘플과 실제 API의 필드명·구조는 같으므로, **바뀌는 것은 `API_BASE` 한 줄**이다.

## 2. 로컬 샘플로 개발하는 방법

브라우저는 보안상 `file://`로 연 HTML에서 `fetch()`로 로컬 JSON을 읽지 못한다. 간단한 로컬 서버를 띄워서 개발한다.

- **방법 A (VS Code):** Live Server 확장 설치 → `index.html` 우클릭 → *Open with Live Server*
- **방법 B (터미널):** 프로젝트 폴더에서 `python -m http.server 5500` 실행 → `http://localhost:5500` 접속

## 3. 코드 예시

```javascript
// 단계에 따라 이 값만 바꾼다
const USE_SAMPLES = true;
const API_BASE = "https://<render-주소>";   // 10/12에 C가 공유

const SAMPLE_FILES = {
  "/scores/latest": "samples/01_scores_latest.json",
  "/scores":        "samples/02_scores_history.json",
  "/indicators":    "samples/03_indicators.json",
  "/health":        "samples/05_health.json",
};

async function getJSON(path, params = {}) {
  let url;
  if (USE_SAMPLES) {
    url = SAMPLE_FILES[path.split("?")[0]] ?? "samples/04_observations.json";
  } else {
    const qs = new URLSearchParams(params).toString();
    url = `${API_BASE}${path}${qs ? "?" + qs : ""}`;
  }

  const res = await fetch(url);
  const body = await res.json().catch(() => null);

  if (!res.ok) {
    // detail은 문자열 또는 배열(422) 두 형태가 모두 올 수 있음
    const d = body?.detail;
    const msg = Array.isArray(d) ? d.map(e => e.msg).join(", ") : (d ?? "알 수 없는 오류");
    throw { status: res.status, message: msg };
  }
  return body;
}

// 사용 예
// const latest  = await getJSON("/scores/latest");
// const history = await getJSON("/scores", { from: "2026-09-01", to: "2026-10-07" });
```

## 4. 화면에서 반드시 처리할 상황

| 상황 | 판단 방법 | 화면 처리 |
|---|---|---|
| 로딩 중 | 요청 후 응답 전 | 로딩 표시 |
| **서버 깨우는 중** | 첫 요청이 10초 이상 걸림 | "서버를 깨우는 중입니다 (최대 1분)" 안내 |
| 데이터 없음 | 404 또는 `items: []` | "조회 가능한 데이터 없음" |
| 입력 오류 | 422 | "기간을 확인해 주세요" |
| 서버 오류 | 500 또는 네트워크 실패 | 오류 문구 + 다시 시도 버튼 |
| 갱신 지연 | `/health`의 `data_status: "stale"` | "마지막 기준일: YYYY-MM-DD" 강조 |
| 값 결측 | 필드가 `null` | `—` 표시 (0으로 표시 금지) |

**서버 깨우는 중:** Render 무료 서버는 15분간 요청이 없으면 잠들고, 다음 첫 요청에 30~60초가 걸릴 수 있다. 오류가 아니라 정상 동작이므로, 타임아웃을 짧게 두지 말고 안내 문구를 보여준다.

## 5. CORS

Vercel 화면(예: `https://xxx.vercel.app`)에서 Render API를 호출하려면 서버에서 허용 설정이 필요하다. C가 다음 주소를 허용 목록에 넣는다.

- `http://localhost:5500`, `http://127.0.0.1:5500` (로컬 개발)
- D의 Vercel 배포 주소 → **배포 후 C에게 알려줄 것**

브라우저 콘솔에 `CORS policy` 오류가 보이면 D의 코드 문제가 아니라 서버 설정 문제이므로 C에게 바로 공유한다.

## 6. 하지 말 것

- 점수·단계·기여도를 브라우저에서 다시 계산하지 않는다.
- API 키나 DB 접속정보를 프론트 코드에 넣지 않는다 (D는 필요하지도 않음).
- 필드명을 바꿔 쓰거나, 샘플에 없는 필드를 가정하지 않는다. 필요한 필드가 있으면 C에게 요청한다.
