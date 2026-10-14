# 금융시장 스트레스 모니터 — D v0.2.1

2026-10-12. D v0.2에 실제 브라우저 검증에서 찾은 문제 6건을 보완한 버전. 실제 서버 연동/배포 완료 버전은 아닙니다.
변경 내역은 ../docs/05_D_v0.2.1_검증보완.md 참조.

## 실행

frontend 폴더에서 `python -m http.server 5500` 실행 후 http://localhost:5500 에 접속합니다.
또는 VS Code Live Server를 사용합니다. index.html을 더블클릭하는 file:// 방식은 샘플 JSON 조회에 적합하지 않습니다.

## 파일 구성

- index.html: 화면 및 정적 방법론
- style.css: 기존 화면 디자인 유지
- app.js: 데이터 조회·검증·표시·최신 요청 우선 처리
- charts.js: SVG 차트, null을 0으로 바꾸지 않고 구간 분리
- samples/: C의 기존 최신 예시 및 D가 확장한 가상 테스트 데이터
- samples/observations/: 5개 지표 상세 샘플
- samples/DEMO_METADATA.json: 데이터 성격과 한계
- ../tests/: Node 회귀 테스트·실행 결과. Vercel 배포 폴더 밖에 둡니다.
- ../docs/: 변경내역 HTML, C 자료 요청 초안

## 샘플 / API

기본값은 USE_SAMPLES:true. 실제 금융데이터처럼 표시하지 않습니다.
일시적 실API 시험: http://localhost:5500/?source=api
API_BASE: https://team7-stress-dashboard.onrender.com
운영 전환은 C의 실제 DB 조회·CORS 확인 후 USE_SAMPLES:false로 변경합니다.
API 주소는 공개 설정이며 FRED 키나 DB 비밀번호는 넣지 않습니다.

## 예외 시나리오

?case=zero / nostage / empty / stale / nohistory / error / slow
zero·nostage는 최신 카드·추이 마지막 값·health 기준일을 맞췄습니다.
nostage는 과거 기준일을 최신으로 가정하는 테스트이며 실제 시장 상태를 뜻하지 않습니다.
기간은 1개월·3개월·1년·전체 범위로 필터링합니다. 조회 종료일은 최신 점수 기준일입니다.

## 데이터 주의

확장된 과거 추이와 지표 관측값은 UI 테스트용 합성 데이터입니다. 실제 FRED 데이터나 B의 산식 결과가 아닙니다.
C의 기존 최신 값과 변화량 예시는 유지했습니다. changes는 확장된 합성 관측 추이에서 계산한 값이 아니므로 산식 검증에 사용하지 마세요.
숫자 0과 결측 null을 구분합니다. /scores에 null 점수가 오면 규격 오류를 안내하며, 차트 함수 자체도 null을 0으로 바꾸지 않습니다.
API numeric 필드는 유한한 number여야 합니다. 숫자 문자열은 잘못된 형식으로 처리합니다.

## 임시 적용안 — 팀 합의 완료 아님

- SHOW_SUMMARY:false: 통합 규격의 해석 제외 권장안에 맞춰 정형 요약 문장을 기본 비표시.
- 백분위 소수 첫째 자리. 반올림으로 단계 경계를 넘어 보이면 '90 미만' 등 표시.
- stage는 API 값 그대로 사용. D에서 위험단계를 다시 계산하지 않음.
- 12.5점 설명, 유효 관측치·동시 관측 용어를 정리. 산식·API 경로 변경 없음.

## 검증

ZIP 최상위 폴더에서 `node tests/test_regression.cjs` 실행. 추가 npm 설치 필요 없음.
테스트는 최소 모의 DOM과 제어된 응답 순서를 사용하는 함수 테스트입니다. 실제 브라우저·CORS·Render 운영 검증을 대체하지 않습니다.
결과는 tests/TEST_RESULTS.txt 참조. 문법검사도 통과했습니다.
실제 브라우저의 모바일·다크 모드·오류/지연 UI 및 5지표 실API 대조는 남아 있습니다.

## 배포

C 저장소의 feature/frontend 브랜치에 frontend/를 반영합니다.
Vercel의 Root Directory는 frontend, 정적 HTML 프로젝트로 설정합니다.
C에게 로컬·미리보기·운영 주소의 CORS 허용을 확인받고 PR로 main 반영을 요청합니다.
실제 배포·병합·팀원 메시지 발송은 이번 작업에서 수행하지 않았습니다.
