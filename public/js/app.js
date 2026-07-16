/*
 * app.js — wires data + Metrics + Charts into the five views.
 * Data comes from window.PRICES_DATA (inlined demo) or data/prices.json.
 */
(() => {
  'use strict';

  // Correlation HORIZON = the rolling window each point is measured over.
  const WINDOWS = [
    { w: 30, label: '30D' }, { w: 60, label: '60D' }, { w: 90, label: '90D' },
    { w: 180, label: '180D' }, { w: 252, label: '1Y' }, { w: 504, label: '2Y' },
    { w: 756, label: '3Y' }, { w: 1260, label: '5Y' },
  ];
  const WINDOW_MAX = 1260;

  // TIME RANGE = how much history the chart shows on its x-axis (independent of
  // the horizon). `years: null` means show everything available.
  const RANGES = [
    { label: '1Y', years: 1 }, { label: '3Y', years: 3 }, { label: '5Y', years: 5 },
    { label: '10Y', years: 10 }, { label: 'Max', years: null },
  ];

  const HORIZON_WORDS = { 30: '30-day', 60: '60-day', 90: '90-day', 180: '180-day', 252: '1-year', 504: '2-year', 756: '3-year', 1260: '5-year' };
  const horizonPhrase = (w) => HORIZON_WORDS[w] || `${w}-day`;

  const state = {
    view: 'matrix',
    window: 90,     // correlation horizon (trading days)
    range: null,    // time range shown (years); null = Max
    pair: { a: null, b: null },
    one: { a: null },
    beta: { base: null, a: null },
    vol: new Set(),
  };

  let DATA, TICKERS, NAMES, DATES, RET;
  let line, heat;
  let applyingHash = false;

  const $ = (id) => document.getElementById(id);
  const seriesColors = () =>
    [1, 2, 3, 4, 5, 6, 7, 8].map((i) => getComputedStyle(document.documentElement).getPropertyValue(`--series-${i}`).trim());
  const fmtCorr = (v) => (v >= 0 ? '+' : '') + v.toFixed(2);
  const fmtBeta = (v) => v.toFixed(2);
  const fmtPct = (v) => (v * 100).toFixed(1) + '%';

  // ---------------------------------------------------------------- bootstrap
  function boot(data) {
    DATA = data;
    TICKERS = Object.keys(data.assets);
    NAMES = data.assets;
    DATES = data.dates;
    RET = Metrics.returnsByAsset(data.prices);

    state.pair = { a: TICKERS[0], b: TICKERS[1] };
    state.one = { a: TICKERS[0] };
    state.beta = { base: TICKERS[0], a: TICKERS[1] };
    state.vol = new Set([TICKERS[0], TICKERS[1]].filter(Boolean));

    $('stamp').textContent = data.generated;
    buildControls();
    line = new Charts.LineChart($('lineHost'));
    heat = new Charts.Heatmap($('heatHost'));

    initTheme();
    wire();
    if (!applyHash()) render();
    window.addEventListener('hashchange', () => { if (!applyingHash) applyHash() && render(); });
  }

  // ----------------------------------------------------------------- controls
  function fillSelect(el, tickers, selected) {
    el.innerHTML = '';
    tickers.forEach((t) => el.options.add(new Option(NAMES[t], t)));
    if (selected) el.value = selected;
  }

  function buildControls() {
    fillSelect($('pairA'), TICKERS, state.pair.a);
    fillSelect($('pairB'), TICKERS, state.pair.b);
    fillSelect($('oneAsset'), TICKERS, state.one.a);
    fillSelect($('betaBase'), TICKERS, state.beta.base);
    fillSelect($('betaAsset'), TICKERS.filter((t) => t !== state.beta.base), state.beta.a);

    const chips = $('wchips');
    chips.innerHTML = '';
    WINDOWS.forEach(({ w, label }) => {
      const b = document.createElement('button');
      b.className = 'wchip'; b.textContent = label; b.dataset.w = w;
      b.addEventListener('click', () => setWindow(w));
      chips.appendChild(b);
    });

    const rchips = $('rchips');
    rchips.innerHTML = '';
    RANGES.forEach(({ label, years }) => {
      const b = document.createElement('button');
      b.className = 'wchip'; b.textContent = label;
      b.dataset.years = years == null ? '' : years;
      b.addEventListener('click', () => setRange(years));
      rchips.appendChild(b);
    });

    const vc = $('volChecks');
    vc.innerHTML = '';
    TICKERS.forEach((t) => {
      const lab = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.value = t; cb.checked = state.vol.has(t);
      cb.addEventListener('change', () => {
        cb.checked ? state.vol.add(t) : state.vol.delete(t);
        render();
      });
      lab.appendChild(cb); lab.appendChild(document.createTextNode(NAMES[t]));
      vc.appendChild(lab);
    });
    syncWindowUI();
    syncRangeUI();
  }

  function syncWindowUI() {
    $('wslider').value = state.window;
    $('wlabel').textContent = state.window;
    document.querySelectorAll('.wchip').forEach((c) => c.classList.toggle('active', +c.dataset.w === state.window));
  }

  function setWindow(w) { state.window = w; syncWindowUI(); render(); }

  function syncRangeUI() {
    document.querySelectorAll('#rchips .wchip').forEach((c) => {
      const y = c.dataset.years === '' ? null : +c.dataset.years;
      c.classList.toggle('active', y === state.range);
    });
  }

  function setRange(years) { state.range = years; syncRangeUI(); render(); }

  // Index of the first visible date given the selected time range (0 = show all).
  function rangeStartIndex() {
    if (state.range == null) return 0;
    const last = DATES[DATES.length - 1];
    const cutoff = (parseInt(last.slice(0, 4), 10) - state.range) + last.slice(4);
    for (let i = 0; i < DATES.length; i++) if (DATES[i] >= cutoff) return i;
    return 0;
  }

  // Slice a line-chart config to the selected time range before drawing.
  // (Metrics are computed over the full history so the rolling lookback is intact;
  //  we only trim what's shown.)
  function setLine(config) {
    const start = rangeStartIndex();
    if (start > 0) {
      config = Object.assign({}, config, {
        dates: config.dates.slice(start),
        series: config.series.map((s) => Object.assign({}, s, { values: s.values.slice(start) })),
      });
    }
    line.setData(config);
  }

  // --------------------------------------------------------------- view logic
  function setView(v) {
    state.view = v;
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === v));
    document.querySelectorAll('[data-controls]').forEach((el) => {
      el.hidden = !el.dataset.controls.split(' ').includes(v);
    });
    $('lineHost').hidden = v === 'matrix';
    $('heatHost').hidden = v !== 'matrix';
    render();
  }

  function setHero(label, value, cls, sub, chips = []) {
    $('heroLabel').textContent = label;
    $('heroSub').textContent = sub || '';
    const el = $('heroValue');
    el.className = 'hero-value' + (cls ? ' ' + cls : '');
    animateNumber(el, value);
    const box = $('heroChips');
    box.innerHTML = '';
    chips.forEach((c) => {
      const d = document.createElement('div');
      d.className = 'chip' + (c.onClick ? ' link' : '');
      d.innerHTML = `<div class="k">${c.k}</div><div class="v">${c.v}</div>`;
      if (c.onClick) d.addEventListener('click', c.onClick);
      box.appendChild(d);
    });
  }

  function animateNumber(el, text) {
    const m = String(text).match(/^([+-]?)(\d+(?:\.\d+)?)(.*)$/);
    if (!m) { el.textContent = text; return; }
    const sign = m[1], target = parseFloat(m[2]), suffix = m[3];
    const decimals = (m[2].split('.')[1] || '').length;
    const start = performance.now(), dur = 520;
    function step(now) {
      const p = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = sign + (target * eased).toFixed(decimals) + suffix;
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function render() {
    updateHash();
    ({ matrix: renderMatrix, pair: renderPair, oneall: renderOne, beta: renderBeta, volatility: renderVol }[state.view])();
  }

  function renderMatrix() {
    const w = state.window;
    const m = Metrics.correlationMatrix(RET, TICKERS, w);
    let best = { v: -2, i: 0, j: 1 }, worst = { v: 2, i: 0, j: 1 }, sum = 0, cnt = 0;
    for (let i = 0; i < TICKERS.length; i++)
      for (let j = i + 1; j < TICKERS.length; j++) {
        const v = m[i][j]; if (v == null) continue;
        if (v > best.v) best = { v, i, j };
        if (v < worst.v) worst = { v, i, j };
        sum += Math.abs(v); cnt++;
      }
    const openPair = (i, j) => { state.pair = { a: TICKERS[i], b: TICKERS[j] }; syncPairSelects(); setView('pair'); };
    heat.setData({ labels: TICKERS.map((t) => NAMES[t]), matrix: m, onSelect: openPair });
    setHero(
      `Strongest pair · ${horizonPhrase(w)} correlation`,
      fmtCorr(best.v), best.v >= 0 ? 'pos' : 'neg',
      `${NAMES[TICKERS[best.i]]} and ${NAMES[TICKERS[best.j]]} — click any cell to inspect`,
      [
        { k: 'Most inverse', v: `${fmtCorr(worst.v)}`, onClick: () => openPair(worst.i, worst.j) },
        { k: 'Avg |ρ|', v: cnt ? (sum / cnt).toFixed(2) : '—' },
      ]
    );
  }

  function renderPair() {
    const { a, b } = state.pair, w = state.window;
    const values = Metrics.rollingCorrelation(RET[a], RET[b], w);
    const latest = Metrics.lastValue(values);
    let lo = Infinity, hi = -Infinity, s = 0, n = 0;
    for (const v of values) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); s += v; n++; }
    setLine({
      dates: DATES,
      series: [{ name: `${NAMES[a]} · ${NAMES[b]}`, values, color: seriesColors()[0] }],
      clampMin: -1, clampMax: 1, format: fmtCorr,
      refLines: [{ y: 0 }], legendEl: $('legend'),
    });
    setHero(
      `${horizonPhrase(w)} rolling correlation`,
      latest == null ? '—' : fmtCorr(latest), latest >= 0 ? 'pos' : 'neg',
      `${NAMES[a]} vs ${NAMES[b]}`,
      n ? [{ k: 'Low', v: fmtCorr(lo) }, { k: 'High', v: fmtCorr(hi) }, { k: 'Mean', v: fmtCorr(s / n) }] : []
    );
  }

  function renderOne() {
    const a = state.one.a, w = state.window;
    const others = TICKERS.filter((t) => t !== a);
    const div = Charts.makeDiverging();
    const series = others.map((t) => {
      const values = Metrics.rollingCorrelation(RET[a], RET[t], w);
      return { t, values, latest: Metrics.lastValue(values) };
    }).sort((x, y) => (y.latest ?? -2) - (x.latest ?? -2));
    setLine({
      dates: DATES,
      series: series.map((s) => ({ name: NAMES[s.t], values: s.values, color: div(s.latest ?? 0) })),
      clampMin: -1, clampMax: 1, format: fmtCorr,
      refLines: [{ y: 0 }], legendEl: $('legend'),
    });
    const top = series[0], bot = series[series.length - 1];
    setHero(
      `${NAMES[a]} vs all · ${horizonPhrase(w)}`,
      top.latest == null ? '—' : fmtCorr(top.latest), (top.latest ?? 0) >= 0 ? 'pos' : 'neg',
      `Strongest correlate right now: ${NAMES[top.t]}`,
      [{ k: 'Most inverse', v: `${NAMES[bot.t]} ${bot.latest == null ? '' : fmtCorr(bot.latest)}` }]
    );
  }

  function renderBeta() {
    const { base, a } = state.beta, w = state.window;
    const values = Metrics.rollingBeta(RET[a], RET[base], w);
    const latest = Metrics.lastValue(values);
    let lo = Infinity, hi = -Infinity, s = 0, n = 0;
    for (const v of values) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); s += v; n++; }
    setLine({
      dates: DATES,
      series: [{ name: `${NAMES[a]} β vs ${NAMES[base]}`, values, color: seriesColors()[0] }],
      format: fmtBeta, refLines: [{ y: 0 }, { y: 1 }], legendEl: $('legend'),
    });
    setHero(
      `${horizonPhrase(w)} rolling beta vs ${NAMES[base]}`,
      latest == null ? '—' : fmtBeta(latest), null,
      `${NAMES[a]} sensitivity to ${NAMES[base]}`,
      n ? [{ k: 'Low', v: fmtBeta(lo) }, { k: 'High', v: fmtBeta(hi) }, { k: 'Mean', v: fmtBeta(s / n) }] : []
    );
  }

  function renderVol() {
    const w = state.window;
    const chosen = TICKERS.filter((t) => state.vol.has(t));
    const colors = seriesColors();
    const series = chosen.map((t, i) => ({
      name: NAMES[t], values: Metrics.rollingVolatility(RET[t], w), color: colors[i % colors.length],
    }));
    setLine({ dates: DATES, series, format: fmtPct, yUnit: 'percent', clampMin: 0, legendEl: $('legend') });
    let hiName = '—', hiVal = null;
    series.forEach((s) => { const v = Metrics.lastValue(s.values); if (v != null && (hiVal == null || v > hiVal)) { hiVal = v; hiName = s.name; } });
    setHero(
      `${horizonPhrase(w)} rolling volatility`,
      hiVal == null ? '—' : fmtPct(hiVal), null,
      chosen.length ? `Highest right now: ${hiName} (annualized)` : 'Select assets below',
      []
    );
  }

  function syncPairSelects() { $('pairA').value = state.pair.a; $('pairB').value = state.pair.b; }

  // -------------------------------------------------------------- hash routing
  function updateHash() {
    const w = state.window;
    const r = state.range == null ? 'max' : state.range;
    let h;
    if (state.view === 'pair') h = `pair?a=${state.pair.a}&b=${state.pair.b}&w=${w}&r=${r}`;
    else if (state.view === 'oneall') h = `oneall?a=${state.one.a}&w=${w}&r=${r}`;
    else if (state.view === 'beta') h = `beta?base=${state.beta.base}&a=${state.beta.a}&w=${w}&r=${r}`;
    else if (state.view === 'volatility') h = `volatility?a=${[...state.vol].join(',')}&w=${w}&r=${r}`;
    else h = `matrix?w=${w}`;
    applyingHash = true;
    history.replaceState(null, '', '#' + h);
    applyingHash = false;
  }

  function applyHash() {
    const raw = location.hash.replace(/^#/, '');
    if (!raw) return false;
    const [view, query = ''] = raw.split('?');
    if (!['matrix', 'pair', 'oneall', 'beta', 'volatility'].includes(view)) return false;
    const q = Object.fromEntries(new URLSearchParams(query));
    const ok = (t) => TICKERS.includes(t);
    if (q.w) state.window = Math.max(20, Math.min(WINDOW_MAX, +q.w || 90));
    if (q.r) state.range = q.r === 'max' ? null : (RANGES.some((x) => x.years === +q.r) ? +q.r : null);
    if (view === 'pair' && ok(q.a) && ok(q.b)) state.pair = { a: q.a, b: q.b };
    if (view === 'oneall' && ok(q.a)) state.one = { a: q.a };
    if (view === 'beta' && ok(q.base) && ok(q.a)) state.beta = { base: q.base, a: q.a };
    if (view === 'volatility' && q.a) { const s = q.a.split(',').filter(ok); if (s.length) state.vol = new Set(s); }
    syncControlsFromState();
    setView(view);
    return true;
  }

  function syncControlsFromState() {
    syncPairSelects();
    $('oneAsset').value = state.one.a;
    $('betaBase').value = state.beta.base;
    fillSelect($('betaAsset'), TICKERS.filter((t) => t !== state.beta.base), state.beta.a);
    document.querySelectorAll('#volChecks input').forEach((cb) => (cb.checked = state.vol.has(cb.value)));
    syncWindowUI();
    syncRangeUI();
  }

  // ---------------------------------------------------------------- theme + wire
  // localStorage can throw in sandboxed iframes / privacy mode — guard it.
  const lsGet = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };

  function initTheme() {
    const saved = lsGet('theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
    updateThemeLabel();
  }
  function updateThemeLabel() {
    const cur = document.documentElement.getAttribute('data-theme')
      || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    $('themeToggle').textContent = cur === 'dark' ? 'Light' : 'Dark';
  }
  function toggleTheme() {
    const cur = document.documentElement.getAttribute('data-theme')
      || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    lsSet('theme', next);
    updateThemeLabel();
    render(); // recompute colors from CSS vars
  }

  function wire() {
    document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => setView(t.dataset.view)));
    $('themeToggle').addEventListener('click', toggleTheme);
    $('wslider').addEventListener('input', (e) => { state.window = +e.target.value; syncWindowUI(); render(); });
    $('pairA').addEventListener('change', (e) => { state.pair.a = e.target.value; render(); });
    $('pairB').addEventListener('change', (e) => { state.pair.b = e.target.value; render(); });
    $('oneAsset').addEventListener('change', (e) => { state.one.a = e.target.value; render(); });
    $('betaBase').addEventListener('change', (e) => {
      state.beta.base = e.target.value;
      if (state.beta.a === state.beta.base) state.beta.a = TICKERS.find((t) => t !== state.beta.base);
      fillSelect($('betaAsset'), TICKERS.filter((t) => t !== state.beta.base), state.beta.a);
      render();
    });
    $('betaAsset').addEventListener('change', (e) => { state.beta.a = e.target.value; render(); });
  }

  // ------------------------------------------------------------------- load
  function start() {
    if (window.PRICES_DATA) return boot(window.PRICES_DATA);
    fetch('data/prices.json')
      .then((r) => { if (!r.ok) throw new Error('prices.json missing'); return r.json(); })
      .then(boot)
      .catch((err) => {
        $('heroLabel').textContent = 'No data';
        $('heroValue').textContent = '—';
        $('heroSub').textContent = 'Run `python generate.py` to build public/data/prices.json.';
        console.error(err);
      });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
