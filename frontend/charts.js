/* =========================================================
   charts.js · 외부 라이브러리 없이 SVG로 그리는 차트 2종
   - Charts.stacked : 시장별 점수 누적 영역 + 종합점수 선
   - Charts.line    : 원천지표 추이 (null이면 선이 끊김)
   공통: 크로스헤어 + 툴팁, 키보드(←/→) 이동, 리사이즈 대응
   ========================================================= */
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const M = { top: 14, right: 14, bottom: 30, left: 40 };

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  /* 날짜 축 라벨: 기간이 길면 연·월, 짧으면 월·일 */
  function dateLabeler(dates) {
    if (dates.length < 2) return (d) => d.slice(5).replace("-", ".");
    const span = (new Date(dates[dates.length - 1]) - new Date(dates[0])) / 86400000;
    if (span > 400) return (d) => d.slice(2, 7).replace("-", ".");
    return (d) => d.slice(5).replace("-", ".");
  }

  function pickTicks(n, maxTicks) {
    if (n <= 1) return [0];
    const step = Math.max(1, Math.ceil((n - 1) / (maxTicks - 1)));
    const out = [];
    for (let i = 0; i < n; i += step) out.push(i);
    if (out[out.length - 1] !== n - 1) {
      if (n - 1 - out[out.length - 1] < step * 0.6) out.pop();
      out.push(n - 1);
    }
    return out;
  }

  function niceTicks(min, max, count) {
    if (min === max) { min -= 1; max += 1; }
    const raw = (max - min) / Math.max(1, count - 1);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }

  /* ---------- 툴팁 ---------- */
  const tip = {
    node: null,
    show(html, clientX, clientY) {
      if (!this.node) this.node = document.getElementById("tooltip");
      if (!this.node) return;
      this.node.innerHTML = html;
      this.node.hidden = false;
      const r = this.node.getBoundingClientRect();
      let x = clientX + 16;
      let y = clientY - r.height - 12;
      if (x + r.width > window.innerWidth - 8) x = clientX - r.width - 16;
      if (x < 8) x = 8;
      if (y < 8) y = clientY + 16;
      this.node.style.left = x + "px";
      this.node.style.top = y + "px";
    },
    hide() { if (this.node) this.node.hidden = true; },
  };

  /* ---------- 공통 상호작용 ---------- */
  function attachHover(container, svg, ctx) {
    const { n, xAt, top, bottom, onIndex, tooltipHtml } = ctx;
    const g = el("g", { "aria-hidden": "true" }, svg);
    const line = el("line", { class: "crosshair", y1: top, y2: bottom, visibility: "hidden" }, g);
    const markers = el("g", {}, g);
    let current = -1;

    function setIndex(i, clientX, clientY) {
      if (i < 0 || i >= n) return;
      current = i;
      const x = xAt(i);
      line.setAttribute("x1", x);
      line.setAttribute("x2", x);
      line.setAttribute("visibility", "visible");
      while (markers.firstChild) markers.removeChild(markers.firstChild);
      onIndex(i, markers);
      const box = svg.getBoundingClientRect();
      const cx = clientX != null ? clientX : box.left + x;
      const cy = clientY != null ? clientY : box.top + top + 20;
      tip.show(tooltipHtml(i), cx, cy);
    }
    function clear() {
      current = -1;
      line.setAttribute("visibility", "hidden");
      while (markers.firstChild) markers.removeChild(markers.firstChild);
      tip.hide();
    }
    function indexFromEvent(e) {
      const box = svg.getBoundingClientRect();
      const px = e.clientX - box.left;
      let best = 0, bestD = Infinity;
      for (let i = 0; i < n; i++) {
        const d = Math.abs(xAt(i) - px);
        if (d < bestD) { bestD = d; best = i; }
      }
      return best;
    }

    const hit = el("rect", {
      x: ctx.left - 8, y: top, width: Math.max(0, ctx.right - ctx.left + 16),
      height: Math.max(0, bottom - top), fill: "transparent",
    }, svg);
    hit.addEventListener("pointermove", (e) => setIndex(indexFromEvent(e), e.clientX, e.clientY));
    hit.addEventListener("pointerdown", (e) => setIndex(indexFromEvent(e), e.clientX, e.clientY));
    hit.addEventListener("pointerleave", clear);

    container.onkeydown = (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const next = current < 0 ? n - 1 : current + (e.key === "ArrowRight" ? 1 : -1);
        setIndex(Math.max(0, Math.min(n - 1, next)));
      } else if (e.key === "Escape") clear();
    };
    container.onblur = clear;
  }

  function frame(container) {
    container.innerHTML = "";
    const w = container.clientWidth || 600;
    const h = container.clientHeight || 300;
    const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h }, container);
    return { svg, w, h, top: M.top, bottom: h - M.bottom, left: M.left, right: w - M.right };
  }

  function drawXAxis(svg, f, dates, xAt) {
    const label = dateLabeler(dates);
    const maxTicks = Math.max(2, Math.floor((f.right - f.left) / 78));
    const ax = el("g", { class: "axis" }, svg);
    pickTicks(dates.length, maxTicks).forEach((i, k, arr) => {
      const anchor = arr.length > 1 && k === 0 ? "start" : (k === arr.length - 1 && arr.length > 1 ? "end" : "middle");
      el("text", { x: xAt(i), y: f.bottom + 20, "text-anchor": dates.length === 1 ? "middle" : anchor }, ax).textContent = label(dates[i]);
    });
  }

  function drawYGrid(svg, f, ticks, yAt, fmt) {
    const grid = el("g", { class: "grid" }, svg);
    const ax = el("g", { class: "axis" }, svg);
    ticks.forEach((t, k) => {
      const y = yAt(t);
      el("line", { x1: f.left, x2: f.right, y1: y, y2: y, class: k === 0 ? "zero" : "" }, grid);
      el("text", { x: f.left - 8, y: y + 4, "text-anchor": "end" }, ax).textContent = fmt(t);
    });
  }

  /* =========================================================
     누적 영역 차트
     opts = { items:[{as_of_date,total_score,markets:{...}}],
              series:[{key,label,colorVar}], yMax, tooltip(i) }
     ========================================================= */
  function stacked(container, opts) {
    const draw = () => {
      const { items, series, yMax = 100 } = opts;
      const f = frame(container);
      const n = items.length;
      const dates = items.map((d) => d.as_of_date);
      const innerW = f.right - f.left;
      const xAt = (i) => (n === 1 ? f.left + innerW / 2 : f.left + (i * innerW) / (n - 1));
      const yAt = (v) => f.bottom - (v / yMax) * (f.bottom - f.top);
      const surface = cssVar("--paper");

      drawYGrid(f.svg, f, [0, 25, 50, 75, 100].filter((t) => t <= yMax), yAt, (t) => t);

      // Split at missing values. Never coerce null to zero, even if called without API validation.
      const valid = v => typeof v === "number" && Number.isFinite(v);
      const cum = items.map(d => {
        if (!series.every(s => valid(d.markets?.[s.key]))) return null;
        let acc=0;
        return series.map(s => {const lo=acc; acc+=d.markets[s.key]; return [lo,acc];});
      });
      function segments(predicate) {
        const groups=[]; let current=[];
        for(let i=0;i<n;i++) {
          if(predicate(i)) current.push(i);
          else if(current.length) {groups.push(current);current=[];}
        }
        if(current.length) groups.push(current);
        return groups;
      }
      const bands=el("g",{},f.svg);
      for(const group of segments(i=>cum[i]!==null)) {
        series.forEach((s,si)=>{
          if(group.length===1) {
            const i=group[0], [lo,hi]=cum[i][si];
            el("rect",{x:xAt(i)-4,y:yAt(hi),width:8,height:Math.max(0,yAt(lo)-yAt(hi)),fill:cssVar(s.colorVar)},bands);
          } else {
            let path=group.map((i,k)=>(k?"L":"M")+xAt(i).toFixed(1)+","+yAt(cum[i][si][1]).toFixed(1)).join("");
            path+=group.slice().reverse().map(i=>"L"+xAt(i).toFixed(1)+","+yAt(cum[i][si][0]).toFixed(1)).join("");
            el("path",{d:path+"Z",fill:cssVar(s.colorVar),"fill-opacity":0.88,stroke:surface,"stroke-width":1},bands);
          }
        });
      }
      for(const group of segments(i=>valid(items[i].total_score))) {
        const d=group.map((i,k)=>(k?"L":"M")+xAt(i).toFixed(1)+","+yAt(items[i].total_score).toFixed(1)).join("");
        el("path",{d,fill:"none",stroke:cssVar("--ink"),"stroke-width":2},f.svg);
        if(group.length===1) {const i=group[0];el("circle",{cx:xAt(i),cy:yAt(items[i].total_score),r:3,fill:cssVar("--ink")},f.svg);}
      }

      drawXAxis(f.svg, f, dates, xAt);

      attachHover(container, f.svg, {
        n, xAt, top: f.top, bottom: f.bottom, left: f.left, right: f.right,
        tooltipHtml: opts.tooltip,
        onIndex(i, g) {
          if (!valid(items[i].total_score)) return;
          el("circle", { cx: xAt(i), cy: yAt(items[i].total_score), r: 5, fill: cssVar("--ink"), stroke: surface, "stroke-width": 2 }, g);
        },
      });
    };
    observe(container, draw);
  }

  /* =========================================================
     선 차트 (원천지표)
     opts = { items:[{obs_date,value}], colorVar, format(v), tooltip(i) }
     ========================================================= */
  function line(container, opts) {
    const draw = () => {
      const { items } = opts;
      const f = frame(container);
      const n = items.length;
      const vals = items.map((d) => (typeof d.value === "number" && Number.isFinite(d.value) ? d.value : null));
      const valid = vals.filter((v) => v != null);
      if (!valid.length) { container.textContent = "이 기간에는 관측값이 없습니다"; return; }
      const dates = items.map((d) => d.obs_date);
      const innerW = f.right - f.left;
      const xAt = (i) => (n === 1 ? f.left + innerW / 2 : f.left + (i * innerW) / (n - 1));
      const lo = Math.min(...valid), hi = Math.max(...valid);
      const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.02 || 1;
      const ticks = niceTicks(lo - pad, hi + pad, 5);
      const yMin = ticks[0], yMax = ticks[ticks.length - 1];
      const yAt = (v) => f.bottom - ((v - yMin) / (yMax - yMin)) * (f.bottom - f.top);
      const color = cssVar(opts.colorVar || "--equity");
      const surface = cssVar("--paper");

      drawYGrid(f.svg, f, ticks, yAt, opts.axisFormat || ((t) => t));

      // null에서 선을 끊는다 (보간하지 않음)
      let d = "", pen = false;
      vals.forEach((v, i) => {
        if (v == null) { pen = false; return; }
        d += (pen ? "L" : "M") + xAt(i).toFixed(1) + "," + yAt(v).toFixed(1);
        pen = true;
      });
      el("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, f.svg);
      // 앞뒤가 비어 있는 외톨이 점은 점으로 표시
      vals.forEach((v, i) => {
        if (v == null) return;
        const prev = i > 0 ? vals[i - 1] : null, next = i < n - 1 ? vals[i + 1] : null;
        if (prev == null && next == null) el("circle", { cx: xAt(i), cy: yAt(v), r: 3, fill: color }, f.svg);
      });

      drawXAxis(f.svg, f, dates, xAt);

      attachHover(container, f.svg, {
        n, xAt, top: f.top, bottom: f.bottom, left: f.left, right: f.right,
        tooltipHtml: opts.tooltip,
        onIndex(i, g) {
          if (vals[i] == null) return;
          el("circle", { cx: xAt(i), cy: yAt(vals[i]), r: 5, fill: color, stroke: surface, "stroke-width": 2 }, g);
        },
      });
    };
    observe(container, draw);
  }

  /* 크기·테마 변경 시 다시 그림 */
  const observers = new WeakMap();
  function observe(container, draw) {
    const prev = observers.get(container);
    if (prev) prev.disconnect();
    let lastW = 0;
    const ro = new ResizeObserver(() => {
      const w = container.clientWidth;
      if (w && Math.abs(w - lastW) > 2) { lastW = w; draw(); }
    });
    ro.observe(container);
    observers.set(container, ro);
    container._redraw = draw;
    draw();
  }

  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    document.querySelectorAll(".chart").forEach((c) => c._redraw && !c.closest("[hidden]") && c._redraw());
  });

  window.Charts = { stacked, line, hideTooltip: () => tip.hide() };
})();
