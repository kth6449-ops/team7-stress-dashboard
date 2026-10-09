-- [A 담당 · 초안] 5개 테이블 생성 + 지표 초기 입력
-- 상세 개발 가이드 v1.1 기준. A가 검토·확정 후 전달본으로 교체.
-- 여러 번 실행해도 오류가 나지 않도록 IF NOT EXISTS / ON CONFLICT 사용.

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
