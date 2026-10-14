/* =========================================================
   app.js · 금융시장 스트레스 모니터 (D 담당)
   - 규격: 「API 규격 정의서 v0.1」, 「통합 개발규격 정의서 v1.0」
   - 원칙: 점수·단계·기여도를 다시 계산하지 않고 API 값을 표시만 함
           null은 "—", 반올림은 화면 표시 때만
   ========================================================= */
(function () {
  "use strict";

  /* ---------------------------------------------------------
     설정: 단계에 따라 여기만 바꾸면 됨
     - 10/10~ : USE_SAMPLES = true  (samples/ 폴더 JSON)
     - 10/12~ : USE_SAMPLES = false (C의 Render API)
     주소창에 ?source=api 또는 ?source=samples 를 붙이면 일시적으로 전환
     --------------------------------------------------------- */
  const CONFIG = {
    USE_SAMPLES: true,
    API_BASE: "https://team7-stress-dashboard.onrender.com",
    WAKE_NOTICE_MS: 8000,        // 이 시간 넘게 응답이 없으면 "서버 깨우는 중" 안내
    REQUEST_TIMEOUT_MS: 90000,   // Render 무료 서버 콜드 스타트를 고려해 길게
    SHOW_SUMMARY: false,         // v0.2 권장안: 팀 합의 전 요약 비표시. C·D 확정 필요
    SPREAD_THRESHOLD: 12.5,      // 막대의 기준선 표시용 (방법론 값과 동일)
    HISTORY_START: "2015-01-01", // "전체" 기간 조회 시작일
  };

  const params = new URLSearchParams(location.search);
  const USE_SAMPLES = params.get("source") === "api" ? false
    : params.get("source") === "samples" ? true : CONFIG.USE_SAMPLES;

  /* 시장·지표 표시 정보 (API의 시장 키는 equity·fx·rate·credit 고정) */
  const MARKETS = [
    { key: "equity", label: "주식", src: "S&P500 · VIX", colorVar: "--equity" },
    { key: "fx",     label: "외환", src: "원/달러 환율", colorVar: "--fx" },
    { key: "rate",   label: "금리", src: "미국 10년물", colorVar: "--rate" },
    { key: "credit", label: "신용", src: "Baa 회사채 금리차", colorVar: "--credit" },
  ];
  const MARKET_BY_KEY = Object.fromEntries(MARKETS.map((m) => [m.key, m]));
  const STAGES = {
    "정상": { cls: "normal" }, "주의": { cls: "caution" },
    "경계": { cls: "alert" },  "위험": { cls: "danger" },
  };

  /* =========================================================
     1. 데이터 가져오기
     ========================================================= */
  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  /* 샘플 모드: 실제 API 경로 → 샘플 파일
     ?case= 로 예외 상황을 바로 확인할 수 있음 (개발·발표 리허설용)
     stale | empty | zero | nostage | error | slow | nohistory */
  const CASE = USE_SAMPLES ? params.get("case") : null;
  function sampleFor(path) {
    const base = path.split("?")[0];
    if (CASE === "error") return { status: 500 };
    if (base === "/health") {
      if (CASE === "stale") return { file: "samples/cases/05_health_stale.json" };
      if (CASE === "empty") return { file: "samples/cases/05_health_empty.json" };
      return { file: CASE === "zero" ? "samples/cases/health_zero.json" : CASE === "nostage" ? "samples/cases/health_nostage.json" : "samples/05_health.json" };
    }
    if (base === "/scores/latest") {
      if (CASE === "empty") return { status: 404, detail: "조회 가능한 데이터가 없습니다." };
      if (CASE === "zero") return { file: "samples/cases/01_scores_latest_total_zero.json" };
      if (CASE === "nostage") return { file: "samples/cases/01_scores_latest_no_stage.json" };
      return { file: "samples/01_scores_latest.json" };
    }
    if (base === "/scores") {
      if (CASE === "empty" || CASE === "nohistory") return { file: "samples/cases/02_scores_history_empty.json" };
      return { file: CASE === "zero" ? "samples/cases/history_zero.json" : CASE === "nostage" ? "samples/cases/history_nostage.json" : "samples/02_scores_history.json" };
    }
    if (base === "/indicators") return { file: CASE === "nostage" ? "samples/cases/indicators_nostage.json" : CASE === "empty" ? "samples/cases/indicators_empty.json" : "samples/03_indicators.json" };
    if (base.startsWith("/indicators/")) {
      const code = base.split("/")[2];
      return { file: `samples/observations/${code}.json` };
    }
    if (base === "/methodology") return { file: "samples/07_methodology.json" };
    return { status: 404, detail: "샘플이 없는 경로입니다." };
  }

  /* 응답 지연 감시 → "서버 깨우는 중" 안내 */
  const wake = {
    pending: 0, timer: null,
    start() {
      this.pending++;
      if (!this.timer) this.timer = setTimeout(() => { if (this.pending) show("#wake-banner"); }, CONFIG.WAKE_NOTICE_MS);
    },
    end() {
      this.pending = Math.max(0, this.pending - 1);
      if (!this.pending) { clearTimeout(this.timer); this.timer = null; hide("#wake-banner"); }
    },
  };

  function detailMessage(detail) {
    if (Array.isArray(detail)) return detail.map((e) => e.msg || JSON.stringify(e)).join(", ");
    return typeof detail === "string" ? detail : "";
  }

  async function getJSON(path, query = {}) {
    let url, mock = null;
    if (USE_SAMPLES) {
      mock = sampleFor(path);
      url = mock.file;
    } else {
      const qs = new URLSearchParams(query).toString();
      url = CONFIG.API_BASE.replace(/\/$/, "") + path + (qs ? "?" + qs : "");
    }

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), CONFIG.REQUEST_TIMEOUT_MS);
    wake.start();
    try {
      if (CASE === "slow") await new Promise((r) => setTimeout(r, CONFIG.WAKE_NOTICE_MS + 3000));
      if (mock && mock.status) {
        throw new ApiError(mock.status, mock.detail || (mock.status === 500 ? "서버 처리 중 오류가 발생했습니다." : ""));
      }
      let res;
      try {
        res = await fetch(url, { signal: ctrl.signal, headers: { Accept: "application/json" } });
      } catch (e) {
        throw new ApiError(0, e.name === "AbortError" ? "응답 시간이 초과되었습니다." : "서버에 연결할 수 없습니다.");
      }
      let body = await res.json().catch(() => null);
      if (!res.ok) throw new ApiError(res.status, detailMessage(body && body.detail));
      validateResponse(path, body);
      if (USE_SAMPLES && query.from && Array.isArray(body.items)) {
        body = {...body, items: body.items.filter(it => {
          const date = it.as_of_date || it.obs_date;
          return date >= query.from && date <= query.to;
        })};
        if (path === "/scores") { body.from = query.from; body.to = query.to; }
      }
      return body;
    } finally {
      clearTimeout(timer);
      wake.end();
    }
  }

  /* =========================================================
     2. 표시 형식 (반올림은 여기서만)
     ========================================================= */
  const isNum = (v) => typeof v === "number" && Number.isFinite(v);
  const DASH = "—";
  const fmt = {
    score: (v) => (isNum(v) ? Number(v).toFixed(1) : DASH),
    pctile: (v) => {
      if (!isNum(v)) return DASH;
      const rounded = Number(v.toFixed(1));
      const crossed = [75,90,95,100].find(t => v < t && rounded >= t);
      return crossed ? `${crossed} 미만` : v.toFixed(1);
    },
    pct1: (v) => (isNum(v) ? Number(v).toFixed(1) + "%" : DASH),
    num(v, digits) {
      return Number(v).toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    },
    value(v, unit) {
      if (!isNum(v)) return DASH;
      switch (unit) {
        case "KRW/USD": return fmt.num(v, 1) + "원";
        case "%": return fmt.num(v, 2) + "%";
        case "%p": return fmt.num(v, 2) + "%p";
        default: return fmt.num(v, 2);
      }
    },
    change(v, unit) {
      if (!isNum(v)) return DASH;
      const n = Number(v);
      const sign = n > 0 ? "+" : n < 0 ? "−" : "";
      return sign + Math.abs(n).toFixed(2) + (unit || "");
    },
    date: (d) => (d ? String(d) : DASH),
    dateTimeKST(iso) {
      if (!iso) return DASH;
      const t = new Date(iso);
      if (Number.isNaN(t.getTime())) return DASH;
      const k = new Date(t.getTime() + 9 * 3600000);
      const p = (x) => String(x).padStart(2, "0");
      return `${k.getUTCFullYear()}-${p(k.getUTCMonth() + 1)}-${p(k.getUTCDate())} ${p(k.getUTCHours())}:${p(k.getUTCMinutes())} (KST)`;
    },
    /* 백분위 → "상위 N%" (92백분위 = 과거 중 상위 8%) */
    topShare(p) {
      if (!isNum(p)) return null;
      const v = Number(p);
      if (v < 50) return `하위 ${Math.max(1, Math.round(v))}%`;
      const top = 100 - v;
      if (top < 1) return "상위 1% 이내";
      // 올림: 표시값이 단계 경계(25·10·5%)를 넘어 보이지 않게 함 (예: 89.6 → 상위 11%, 단계 주의)
      return `상위 ${Math.ceil(top - 1e-9)}%`;
    },
  };


  // Contract validation: do not silently turn invalid payloads into normal scores.
  function validDate(v) {
    if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
    const d = new Date(v + "T00:00:00Z");
    return Number.isFinite(d.getTime()) && d.toISOString().slice(0,10) === v;
  }
  function shiftMonths(date, months) {
    const d = new Date(date + "T00:00:00Z");
    const day = d.getUTCDate();
    d.setUTCDate(1);
    d.setUTCMonth(d.getUTCMonth() + months);
    const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth()+1, 0)).getUTCDate();
    d.setUTCDate(Math.min(day,last));
    return d.toISOString().slice(0,10);
  }
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  function validateResponse(path, d) {
    const object = x => x !== null && typeof x === "object" && !Array.isArray(x);
    const num = (v, lo=-Infinity, hi=Infinity) => isNum(v) && v>=lo && v<=hi;
    const nullable = (v,lo,hi) => v===null || num(v,lo,hi);
    const text = v => typeof v === "string" && v.length>0;
    const markets = m => object(m) && MARKETS.every(k => num(m[k.key],0,25));
    let ok=object(d);
    if (ok && path==="/scores/latest") {
      ok=validDate(d.as_of_date) && text(d.rule_version) && num(d.total_score,0,100)
        && nullable(d.total_percentile,0,100) && (d.stage===null || has(STAGES,d.stage))
        && markets(d.markets) && object(d.contributions)
        && MARKETS.every(k => nullable(d.contributions[k.key],0,100.01))
        && Number.isInteger(d.spread_count) && num(d.spread_count,0,4)
        && typeof d.is_provisional === "boolean";
    } else if (ok && path==="/scores") {
      ok=text(d.rule_version) && validDate(d.from) && validDate(d.to) && d.from<=d.to && Array.isArray(d.items)
        && d.items.every(it => object(it) && validDate(it.as_of_date) && num(it.total_score,0,100) && markets(it.markets));
    } else if (ok && path==="/indicators") {
      ok=Array.isArray(d.items) && d.items.every(it => object(it) && text(it.name)
        && ["DEXKOUS","DGS10","SP500","VIXCLS","BAA10Y"].includes(it.code)
        && has(MARKET_BY_KEY,it.market) && ["KRW/USD","%","index","%p"].includes(it.unit)
        && ["%","%p","pt"].includes(it.change_unit) && (it.obs_date===null || validDate(it.obs_date))
        && nullable(it.value) && object(it.changes) && ["d1","m1","m3"].every(k=>nullable(it.changes[k]))
        && typeof it.source_url === "string" && /^https:\/\//.test(it.source_url));
      if(ok) ok=new Set(d.items.map(it=>it.code)).size===d.items.length;
    } else if (ok && path.startsWith("/indicators/")) {
      ok=d.code===decodeURIComponent(path.split("/")[2]) && text(d.unit) && Array.isArray(d.items)
        && d.items.every(it=>object(it) && validDate(it.obs_date) && nullable(it.value));
    } else if (ok && path==="/health") {
      ok=d.status==="ok" && ["fresh","stale","empty"].includes(d.data_status)
        && (d.latest_as_of_date===null || validDate(d.latest_as_of_date));
    }
    if (!ok) throw new ApiError(502,"서버 응답 형식이 개발 규격과 다릅니다. API 응답을 확인해 주세요.");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /* =========================================================
     3. 화면 상태 도우미 (로딩 · 빈 데이터 · 오류)
     ========================================================= */
  const $ = (sel, root = document) => root.querySelector(sel);
  function show(sel) { const n = typeof sel === "string" ? $(sel) : sel; if (n) n.hidden = false; }
  function hide(sel) { const n = typeof sel === "string" ? $(sel) : sel; if (n) n.hidden = true; }

  function setState(section, bodySel, state, opts = {}) {
    const stateBox = $(".state", section);
    const body = $(bodySel, section);
    if (state === "ready") { hide(stateBox); show(body); return; }
    hide(body);
    show(stateBox);
    stateBox.dataset.state = state;
    if (state === "loading") {
      stateBox.innerHTML = `<div class="skeleton ${opts.skeleton || "skeleton--rows"}"></div>`;
      return;
    }
    const isError = state === "error";
    stateBox.innerHTML = `
      <div class="state-msg ${isError ? "state-msg--error" : ""}" role="${isError ? "alert" : "status"}">
        <strong>${escapeHtml(opts.title || "")}</strong>
        <span>${escapeHtml(opts.message || "")}</span>
        ${opts.retry ? `<div><button type="button" class="btn">다시 시도</button></div>` : ""}
      </div>`;
    if (opts.retry) $(".btn", stateBox).addEventListener("click", opts.retry);
  }

  function errorCopy(err, what) {
    if (err.status === 502) return { state: "error", title: "데이터 형식을 확인해 주세요", message: err.message };
    if (err.status === 404) return { state: "empty", title: `${what}가 아직 없습니다`, message: "첫 데이터 수집과 계산이 끝나면 여기에 표시됩니다." };
    if (err.status === 422) return { state: "error", title: "조회 기간을 확인해 주세요", message: err.message || "날짜 형식이나 기간이 올바르지 않습니다." };
    if (err.status === 0) return { state: "error", title: `${what}를 불러오지 못했습니다`, message: `${err.message} 잠시 후 다시 시도해 주세요.` };
    return { state: "error", title: `${what}를 불러오지 못했습니다`, message: "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요." };
  }

  /* =========================================================
     4. 섹션별 렌더링
     ========================================================= */
  const store = { latest: null, indicators: null, period: "3m", view: "chart", history: null };

  let historyRequest = 0, detailRequest = 0;

  /* ---------- 데이터 상태 (/health) ---------- */
  async function loadHealth() {
    const chip = $("#meta-health");
    try {
      const h = await getJSON("/health");
      const map = {
        fresh: ["fresh", "정상 갱신"],
        stale: ["stale", "갱신 지연"],
        empty: ["empty", "데이터 준비 중"],
      };
      const [cls, text] = map[h.data_status] || ["unknown", "알 수 없음"];
      chip.className = "health health--" + cls;
      chip.textContent = text;
      chip.title = h.last_success_at ? "마지막 정상 갱신 " + fmt.dateTimeKST(h.last_success_at) : "";
      if (h.data_status === "stale") {
        const b = $("#stale-banner");
        b.textContent = `데이터 갱신이 늦어지고 있습니다. 마지막 점수 기준일은 ${fmt.date(h.latest_as_of_date)}입니다.`;
        show(b);
      } else hide("#stale-banner");
    } catch (e) {
      chip.className = "health health--error";
      chip.textContent = "상태 확인 실패";
    }
  }

  /* ---------- 종합 현황 + 시장 진단 (/scores/latest) ---------- */
  async function loadLatest() {
    const ov = $("#overview"), mk = $("#markets");
    setState(ov, ".overview__body", "loading", { skeleton: "skeleton--hero" });
    setState(mk, ".markets__body", "loading");
    try {
      const d = await getJSON("/scores/latest");
      store.latest = d;
      renderOverview(d);
      renderMarkets(d);
      setState(ov, ".overview__body", "ready");
      setState(mk, ".markets__body", "ready");
    } catch (err) {
      store.latest = null;
      $("#meta-asof").textContent = DASH;
      $("#meta-rule").textContent = DASH;
      const c = errorCopy(err, "종합점수");
      setState(ov, ".overview__body", c.state, { ...c, retry: c.state === "error" ? loadLatest : null });
      setState(mk, ".markets__body", c.state, { title: c.state === "empty" ? "시장별 점수가 아직 없습니다" : "시장별 점수를 불러오지 못했습니다", message: c.state === "empty" ? "" : "위의 다시 시도 버튼을 눌러 주세요." });
    }
    // 추이는 최신 기준일을 알아야 기간을 정할 수 있으므로 이후에 호출
    if (store.indicators) renderIndicators(store.indicators, store.indicatorsUpdatedAt);
    loadHistory();   // 기다리지 않음: 추이가 늦어도 지표 표는 먼저 표시
  }

  function renderOverview(d) {
    $("#meta-asof").textContent = fmt.date(d.as_of_date);
    $("#meta-rule").textContent = d.rule_version || DASH;
    $("#total-score").textContent = fmt.score(d.total_score);

    const pill = $("#stage-pill");
    const st = STAGES[d.stage];
    pill.className = "stage stage--" + (st ? st.cls : "none");
    pill.textContent = st ? d.stage : "산출 전";
    $("#stage-note").textContent = st
      ? (d.is_provisional ? "잠정치입니다" : "")
      : "비교할 과거 기간이 아직 짧아 단계를 정하지 않았습니다";

    // 과거 대비 위치 레일
    const marker = $("#rail-marker");
    const rail = $("#rail");
    if (isNum(d.total_percentile)) {
      const p = Math.max(0, Math.min(100, Number(d.total_percentile)));
      marker.style.setProperty("--p", p);
      $("#rail-marker-label").textContent = fmt.pctile(p) + " 백분위";
      marker.classList.toggle("rail__marker--end", p >= 88);
      marker.classList.toggle("rail__marker--start", p <= 12);
      show(marker);
      $("#rail-caption").textContent = `관측 가능한 과거 기간 중 ${fmt.topShare(p)} 수준`;
      rail.setAttribute("aria-label", `과거 대비 위치 ${fmt.pctile(p)} 백분위, ${fmt.topShare(p)}, 단계 ${d.stage || "산출 전"}`);
    } else {
      hide(marker);
      $("#rail-caption").textContent = "백분위 산출 전";
      rail.setAttribute("aria-label", "과거 대비 위치는 아직 산출되지 않았습니다");
    }

    // 한 줄 요약 (API 값을 문장 틀에 넣기만 함)
    const sum = $("#summary");
    if (CONFIG.SHOW_SUMMARY) {
      sum.innerHTML = summaryText(d);
      show(sum);
    } else hide(sum);
  }

  function summaryText(d) {
    const c = d.contributions || {};
    const keys = MARKETS.map((m) => m.key).filter((k) => isNum(c[k]));
    if (!keys.length) {
      return d.total_score === 0 ? `종합점수가 0점이라 시장별 기여도는 표시하지 않습니다.` : `시장별 기여도 데이터가 없습니다.`;
    }
    if (keys.length !== MARKETS.length) return `일부 시장의 기여도 데이터가 없어 최대 기여 시장을 표시하지 않습니다.`;
    const top = keys.reduce((a, b) => (Number(c[b]) > Number(c[a]) ? b : a));
    const n = d.spread_count;
    const spread = !isNum(n) ? ""
      : Number(n) === 0 ? " 높은 스트레스 구간에 있는 시장은 없습니다."
      : ` 네 시장 중 <b>${n}개</b>에서 높은 스트레스가 동시에 나타나고 있습니다.`;
    return `<b>${MARKET_BY_KEY[top].label}</b> 시장이 종합점수의 ${fmt.pct1(c[top])}를 차지해 가장 크게 기여하고 있습니다.${spread}`;
  }

  function renderMarkets(d) {
    const list = $("#market-list");
    const c = d.contributions || {};
    list.innerHTML = MARKETS.map((m) => {
      const v = d.markets ? d.markets[m.key] : null;
      const high = isNum(v) && Number(v) >= CONFIG.SPREAD_THRESHOLD;
      const width = isNum(v) ? Math.max(0, Math.min(25, Number(v))) : 0;
      return `
        <li class="market">
          <div>
            <span class="market__name"><i class="dot" style="--c:var(${m.colorVar})"></i>${m.label}${high ? '<span class="tag-high">높음</span>' : ""}</span>
            <span class="market__src">${escapeHtml(m.src)}</span>
          </div>
          <div class="bar" role="img" aria-label="${m.label} ${fmt.score(v)}점, 최대 25점">
            <div class="bar__fill" style="--c:var(${m.colorVar});--v:${width}"></div>
            <div class="bar__tick" title="기준선 ${CONFIG.SPREAD_THRESHOLD}점"></div>
          </div>
          <div class="market__score">${fmt.score(v)}<small> / 25</small></div>
          <div class="market__contrib">기여 ${fmt.pct1(c[m.key])}</div>
        </li>`;
    }).join("") + `
      <li class="bar-scale" aria-hidden="true"><div></div><div><span style="left:0;transform:none">0</span><span style="left:50%">12.5 기준선</span><span style="left:100%;transform:translateX(-100%)">25</span></div><div></div><div></div></li>`;

    // 동시 스트레스 시장 수
    $("#spread-count").textContent = isNum(d.spread_count) ? d.spread_count : DASH;
    $("#spread-pips").innerHTML = MARKETS.map((m) => {
      const v = d.markets ? d.markets[m.key] : null;
      const on = isNum(v) && Number(v) >= CONFIG.SPREAD_THRESHOLD;
      return `<span class="pip ${on ? "pip--on" : ""}" style="--c:var(${m.colorVar})" title="${m.label}"></span>`;
    }).join("");
    const n = Number(d.spread_count);
    $("#spread-note").textContent = !isNum(d.spread_count) ? ""
      : n === 0 ? "기준선(12.5점) 이상인 시장이 없습니다"
      : n === 1 ? "한 시장에 국한된 스트레스입니다"
      : n === 2 ? "두 시장에서 동시에 높습니다"
      : "여러 시장에서 높은 스트레스가 동시에 관측됩니다";

    // 기여도 막대
    const bar = $("#contrib-bar");
    const keys = MARKETS.filter((m) => isNum(c[m.key]) && Number(c[m.key]) > 0);
    if (keys.length === 0 || MARKETS.some(m => !isNum(c[m.key]))) {
      bar.innerHTML = `<div class="contrib__empty">${d.total_score === 0 ? "종합점수가 0점이라 기여도가 없습니다" : "시장별 기여도 데이터가 없습니다"}</div>`;
      bar.setAttribute("aria-label", "기여도 없음");
    } else {
      bar.innerHTML = keys.map((m) =>
        `<div class="contrib__seg" style="--c:var(${m.colorVar});flex:${Number(c[m.key])}" title="${m.label} ${fmt.pct1(c[m.key])}"></div>`).join("");
      bar.setAttribute("aria-label", "종합점수 기여도: " + MARKETS.map((m) => `${m.label} ${fmt.pct1(c[m.key])}`).join(", "));
    }
    $("#contrib-legend").innerHTML = MARKETS.map((m) =>
      `<li><i class="dot" style="--c:var(${m.colorVar})"></i>${m.label}<b>${fmt.pct1(c[m.key])}</b></li>`).join("");
  }

  /* ---------- 점수 추이 (/scores?from=&to=) ---------- */
  function periodRange(period) {
    const toStr = store.latest?.as_of_date || todayKST();
    const months = {"1m":1,"3m":3,"1y":12}[period];
    return {from: months ? shiftMonths(toStr,-months) : CONFIG.HISTORY_START, to:toStr};
  }

  function todayKST() {
    return new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
  }

  async function loadHistory() {
    const request = ++historyRequest;
    const sec = $("#trend");
    setState(sec, ".trend__body", "loading", { skeleton: "skeleton--chart" });
    const range = periodRange(store.period);
    try {
      const d = await getJSON("/scores", range);
      if (request !== historyRequest) return;
      store.history = d;
      const items = (d.items || []).slice().sort((a, b) => (a.as_of_date < b.as_of_date ? -1 : 1));
      if (!items.length) {
        setState(sec, ".trend__body", "empty", { title: "이 기간에는 계산된 점수가 없습니다", message: "다른 기간을 선택해 보세요." });
        return;
      }
      setState(sec, ".trend__body", "ready");
      renderTrend(items);
      $("#trend-range").textContent =
        `${items[0].as_of_date} ~ ${items[items.length - 1].as_of_date}, ${items.length}개 기준일. 점수가 없는 날은 건너뜁니다.`;
    } catch (err) {
      if (request !== historyRequest) return;
      store.history = null;
      const c = errorCopy(err, "점수 추이");
      setState(sec, ".trend__body", c.state, { ...c, retry: c.state === "error" ? loadHistory : null });
    }
  }

  function renderTrend(items) {
    $("#trend-legend").innerHTML =
      MARKETS.map((m) => `<li><i class="dot" style="--c:var(${m.colorVar})"></i>${m.label}</li>`).join("") +
      `<li><span class="line-key"></span>종합점수</li>`;

    const chartBox = $("#trend-chart"), tableBox = $("#trend-table");
    if (store.view === "table") {
      hide(chartBox); show(tableBox);
      tableBox.innerHTML = `
        <table class="data-table">
          <thead><tr><th scope="col">기준일</th><th scope="col" class="num">종합</th>
          ${MARKETS.map((m) => `<th scope="col" class="num">${m.label}</th>`).join("")}</tr></thead>
          <tbody>${items.slice().reverse().map((it) => `
            <tr><td>${it.as_of_date}</td><td class="num"><b>${fmt.score(it.total_score)}</b></td>
            ${MARKETS.map((m) => `<td class="num">${fmt.score(it.markets?.[m.key])}</td>`).join("")}</tr>`).join("")}
          </tbody>
        </table>`;
      return;
    }
    show(chartBox); hide(tableBox);
    Charts.stacked(chartBox, {
      items,
      series: MARKETS,
      yMax: 100,
      tooltip: (i) => {
        const it = items[i];
        return `<div class="tooltip__date">${it.as_of_date}</div>` +
          MARKETS.slice().reverse().map((m) =>
            `<div class="tooltip__row"><span><i class="dot" style="--c:var(${m.colorVar})"></i>${m.label}</span><b>${fmt.score(it.markets?.[m.key])}</b></div>`).join("") +
          `<div class="tooltip__row tooltip__total"><span>종합점수</span><b>${fmt.score(it.total_score)}</b></div>`;
      },
    });
  }

  /* ---------- 금융지표 (/indicators) ---------- */
  const IND_SUB = {
    DEXKOUS: "외환", DGS10: "금리", SP500: "주식", VIXCLS: "주식", BAA10Y: "신용",
  };

  async function loadIndicators(waitFor) {
    const sec = $("#indicators");
    setState(sec, ".indicators__body", "loading");
    try {
      const [d] = await Promise.all([getJSON("/indicators"), (waitFor || Promise.resolve()).catch(() => null)]);
      const items = d.items || [];
      store.indicators = items;
      store.indicatorsUpdatedAt = d.updated_at;
      if (!items.length) {
        setState(sec, ".indicators__body", "empty", { title: "표시할 지표가 없습니다", message: "데이터 수집이 끝나면 표시됩니다." });
        return;
      }
      renderIndicators(items, d.updated_at);
      renderSources(items);
      setState(sec, ".indicators__body", "ready");
    } catch (err) {
      const c = errorCopy(err, "금융지표");
      setState(sec, ".indicators__body", c.state, { ...c, retry: c.state === "error" ? () => loadIndicators() : null });
    }
  }

  function renderIndicators(items, updatedAt) {
    const asOf = store.latest?.as_of_date;
    $("#ind-rows").innerHTML = items.map((it) => {
      const market = MARKET_BY_KEY[it.market];
      const cls = (v) => (!isNum(v) ? "" : Number(v) > 0 ? "chg chg--up" : Number(v) < 0 ? "chg chg--down" : "chg");
      const ch = it.changes || {};
      const lag = asOf && it.obs_date && it.obs_date < asOf;
      return `
        <tr data-code="${escapeHtml(it.code)}" tabindex="0" aria-label="${escapeHtml(it.name)} 추이 보기">
          <td><span class="ind-name">${market ? `<i class="dot" style="--c:var(${market.colorVar})"></i>` : ""}${escapeHtml(it.name)}
            <small>${escapeHtml(it.code)} · ${IND_SUB[it.code] || market?.label || ""}</small></span></td>
          <td class="num ind-value">${fmt.value(it.value, it.unit)}</td>
          <td class="num"><span class="${cls(ch.d1)}">${fmt.change(ch.d1, it.change_unit)}</span></td>
          <td class="num"><span class="${cls(ch.m1)}">${fmt.change(ch.m1, it.change_unit)}</span></td>
          <td class="num"><span class="${cls(ch.m3)}">${fmt.change(ch.m3, it.change_unit)}</span></td>
          <td>${fmt.date(it.obs_date)}${lag ? '<span class="lag" title="점수 기준일보다 이전 관측값">기준일 이전</span>' : ""}</td>
        </tr>`;
    }).join("");
    $("#ind-updated").textContent =
      `변화는 직전·21개·63개 이전 관측치와 비교한 값입니다. 환율·S&P500은 %, 금리·신용은 %p, VIX는 포인트입니다. 갱신 ${fmt.dateTimeKST(updatedAt)}`;

    $("#ind-rows").querySelectorAll("tr").forEach((tr) => {
      const open = () => openDetail(tr.dataset.code);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
  }

  function renderSources(items) {
    $("#sources").innerHTML = items.map((it) =>
      `<li>${escapeHtml(it.name)}: <a href="${escapeHtml(it.source_url)}" target="_blank" rel="noopener">FRED ${escapeHtml(it.code)}</a></li>`).join("") +
      `<li>제공: Federal Reserve Bank of St. Louis (FRED)</li>`;
  }

  /* ---------- 지표 상세 (/indicators/{code}/observations) ---------- */
  async function openDetail(code) {
    const request = ++detailRequest;
    const it = (store.indicators || []).find((x) => x.code === code);
    if (!it) return;
    document.querySelectorAll("#ind-rows tr").forEach((tr) => tr.classList.toggle("is-active", tr.dataset.code === code));
    const box = $("#ind-detail");
    show(box);
    $("#detail-title").textContent = `${it.name} 추이`;
    setState(box, ".detail__body", "loading", { skeleton: "skeleton--chart" });

    const to = it.obs_date || todayKST();
    const fromDate = shiftMonths(to, -12);
    try {
      const d = await getJSON(`/indicators/${encodeURIComponent(code)}/observations`, { from: fromDate, to });
      if (request !== detailRequest) return;
      const items = (d.items || []).slice().sort((a,b)=>a.obs_date.localeCompare(b.obs_date));
      if (!items.some((x) => isNum(x.value))) {
        setState(box, ".detail__body", "empty", { title: "이 기간에는 관측값이 없습니다", message: "" });
        return;
      }
      setState(box, ".detail__body", "ready");
      const market = MARKET_BY_KEY[it.market];
      const unit = d.unit || it.unit;
      Charts.line($("#detail-chart"), {
        items,
        colorVar: market ? market.colorVar : "--equity",
        axisFormat: (t) => fmt.num(t, Math.abs(t) >= 100 ? 0 : 2),
        tooltip: (i) => `<div class="tooltip__date">${items[i].obs_date}</div>
          <div class="tooltip__row"><span>${escapeHtml(it.name)}</span><b>${isNum(items[i].value) ? fmt.value(items[i].value, unit) : "휴장·결측"}</b></div>`,
      });
      $("#detail-chart").setAttribute("aria-label", `${it.name} 추이 차트. 좌우 화살표로 날짜를 이동할 수 있습니다.`);
      const nulls = items.filter((x) => !isNum(x.value)).length;
      $("#detail-note").textContent =
        `${items[0].obs_date} ~ ${items[items.length - 1].obs_date}` + (nulls ? `, 휴장·결측 ${nulls}일은 선을 끊어 표시` : "");
      box.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
    } catch (err) {
      if (request !== detailRequest) return;
      const c = errorCopy(err, "지표 추이");
      setState(box, ".detail__body", c.state, { ...c, retry: c.state === "error" ? () => openDetail(code) : null });
    }
  }

  /* =========================================================
     5. 이벤트 · 시작
     ========================================================= */
  function bindControls() {
    document.querySelectorAll("[data-period]").forEach((b) => b.addEventListener("click", () => {
      if (store.period === b.dataset.period) return;
      store.period = b.dataset.period;
      document.querySelectorAll("[data-period]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      loadHistory();
    }));
    document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
      store.view = b.dataset.view;
      document.querySelectorAll("[data-view]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      const items = (store.history?.items || []).slice().sort((a, b2) => (a.as_of_date < b2.as_of_date ? -1 : 1));
      if (items.length) renderTrend(items);
    }));
    $("#detail-close").addEventListener("click", () => {
      detailRequest++;
      hide("#ind-detail");
      Charts.hideTooltip();
      document.querySelectorAll("#ind-rows tr").forEach((tr) => tr.classList.remove("is-active"));
    });
    window.addEventListener("scroll", () => Charts.hideTooltip(), { passive: true });
  }

  function init() {
    if (USE_SAMPLES) show("#sample-banner");
    bindControls();
    loadHealth();
    const latest = loadLatest();   // 끝나면 loadHistory() 호출
    loadIndicators(latest);        // 점수 기준일과 지표 관측일을 비교하기 위해 함께 기다림
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
