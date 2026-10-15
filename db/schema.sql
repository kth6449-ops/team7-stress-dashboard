-- [A 담당 · 검토본 v0.1] 5개 테이블 생성 + 지표 초기 입력
-- C 초안(상세 개발 가이드 v1.1 기준)을 그대로 유지하고, 아래 2건만 추가함.
--   + observations(obs_date) 인덱스: 날짜 범위 조회(/scores, /observations?from=&to=) 속도용
--   + 5개 테이블 RLS 활성화 (맨 아래): Supabase 자동 공개 API로 외부에서 읽고 쓰는 것을 차단
-- 여러 번 실행해도 오류가 나지 않도록 IF NOT EXISTS / ON CONFLICT 사용.
-- 주의: DROP / DELETE / TRUNCATE 문은 넣지 않음 (S&P500 과거 데이터 보존)

CREATE TABLE IF NOT EXISTS indicators (
    code        text PRIMARY KEY,           -- FRED ID
    name        text NOT NULL,
    market      text NOT NULL CHECK (market IN ('equity','fx','rate','credit')),
    unit        text NOT NULL,
    source_url  text
);

CREATE TABLE IF NOT EXISTS observations (
    code        text NOT NULL REFERENCES indicators(code),
    obs_date    date NOT NULL,
    value       numeric,                    -- 결측이면 NULL (0 아님)
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (code, obs_date)
);

CREATE INDEX IF NOT EXISTS observations_obs_date_idx ON observations (obs_date);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trigger      text NOT NULL CHECK (trigger IN ('manual','schedule')),
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    status       text NOT NULL CHECK (status IN ('running','success','failed')),
    rows_written integer,
    error        text
);

CREATE TABLE IF NOT EXISTS indicator_score (
    code          text NOT NULL REFERENCES indicators(code),
    as_of_date    date NOT NULL,
    rule_version  text NOT NULL,
    stress_value  numeric,
    percentile    numeric,
    score         numeric,
    computed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (code, as_of_date, rule_version)
);

CREATE TABLE IF NOT EXISTS daily_scores (
    as_of_date        date NOT NULL,
    rule_version      text NOT NULL,
    equity_score      numeric,
    fx_score          numeric,
    rate_score        numeric,
    credit_score      numeric,
    total_score       numeric,
    total_percentile  numeric,              -- 비교 기간 부족 시 NULL
    stage             text CHECK (stage IN ('정상','주의','경계','위험')),
    spread_count      integer,
    is_provisional    boolean NOT NULL DEFAULT false,
    computed_at       timestamptz NOT NULL DEFAULT now(),
    run_id            bigint REFERENCES pipeline_runs(run_id),
    PRIMARY KEY (as_of_date, rule_version)
);

INSERT INTO indicators (code, name, market, unit, source_url) VALUES
    ('DEXKOUS', '원/달러 환율',              'fx',     'KRW/USD', 'https://fred.stlouisfed.org/series/DEXKOUS'),
    ('DGS10',   '미국 10년물 국채금리',       'rate',   '%',       'https://fred.stlouisfed.org/series/DGS10'),
    ('SP500',   'S&P500 지수',              'equity', 'index',   'https://fred.stlouisfed.org/series/SP500'),
    ('VIXCLS',  'VIX 변동성지수',            'equity', 'index',   'https://fred.stlouisfed.org/series/VIXCLS'),
    ('BAA10Y',  'Baa 회사채-10년물 금리차',   'credit', '%p',      'https://fred.stlouisfed.org/series/BAA10Y')
ON CONFLICT (code) DO NOTHING;

-- [A 추가] Supabase 자동 REST API(Data API) 차단용 보안 설정
-- Supabase는 public 스키마의 테이블을 웹 API로 자동 공개하므로, RLS를 켜서 외부 접근을 막음.
-- 우리 서비스는 DATABASE_URL(postgres 계정)로 직접 접속하며, 테이블 소유자라 RLS 영향을 받지 않음.
ALTER TABLE indicators      ENABLE ROW LEVEL SECURITY;
ALTER TABLE observations    ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE indicator_score ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_scores    ENABLE ROW LEVEL SECURITY;
