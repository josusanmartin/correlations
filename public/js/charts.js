/*
 * charts.js — self-contained canvas chart engine (no external libraries).
 *
 * Two chart types, both retina-aware, theme-driven (they read CSS custom
 * properties so light/dark works), and responsive via ResizeObserver:
 *   - LineChart : multi-series time series with crosshair + HTML tooltip.
 *   - Heatmap   : correlation matrix with a diverging scale + cell tooltip.
 *
 * Exposed as the global `Charts`.
 */
const Charts = (() => {
  'use strict';

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function hexToRgb(hex) {
    hex = hex.replace('#', '');
    if (hex.length === 3) hex = hex.split('').map((c) => c + c).join('');
    const n = parseInt(hex, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function lerpRgb(a, b, t) {
    return `rgb(${Math.round(a[0] + (b[0] - a[0]) * t)},${Math.round(a[1] + (b[1] - a[1]) * t)},${Math.round(a[2] + (b[2] - a[2]) * t)})`;
  }

  // Diverging scale for correlation-like values in [-1, 1].
  function makeDiverging() {
    const neg = hexToRgb(cssVar('--div-neg'));
    const mid = hexToRgb(cssVar('--div-mid'));
    const pos = hexToRgb(cssVar('--div-pos'));
    return (t) => {
      if (t == null || Number.isNaN(t)) return cssVar('--cell-empty');
      const c = Math.max(-1, Math.min(1, t));
      return c < 0 ? lerpRgb(mid, neg, -c) : lerpRgb(mid, pos, c);
    };
  }

  // "Nice" axis ticks (~count of them) covering [min, max].
  function niceTicks(min, max, count = 5) {
    if (min === max) { min -= 1; max += 1; }
    const span = max - min;
    const step0 = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const norm = step0 / mag;
    const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
    const start = Math.ceil(min / step) * step;
    const ticks = [];
    for (let v = start; v <= max + step * 1e-6; v += step) ticks.push(Math.abs(v) < step * 1e-6 ? 0 : v);
    return ticks;
  }

  function formatMonth(dateStr) {
    const [y, m] = dateStr.split('-');
    return `${MONTHS[+m - 1]} '${y.slice(2)}`;
  }

  function setupCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width));
    const h = Math.max(1, Math.floor(rect.height));
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
  }

  // ------------------------------------------------------------------ LineChart
  class LineChart {
    constructor(container) {
      this.container = container;
      this.canvas = document.createElement('canvas');
      this.canvas.className = 'chart-canvas';
      this.tooltip = document.createElement('div');
      this.tooltip.className = 'chart-tooltip';
      this.tooltip.style.display = 'none';
      container.appendChild(this.canvas);
      container.appendChild(this.tooltip);
      this.data = null;
      this.hover = null;

      this._onMove = (e) => this._move(e);
      this._onLeave = () => { this.hover = null; this.tooltip.style.display = 'none'; this.render(); };
      this.canvas.addEventListener('mousemove', this._onMove);
      this.canvas.addEventListener('mouseleave', this._onLeave);

      this._ro = new ResizeObserver(() => this.render());
      this._ro.observe(container);
    }

    setData(data) {
      // data: { dates:[], series:[{name,values,color}], format(v), yDomain?, refLines?:[{y,label}] }
      this.data = data;
      this.hover = null;
      this._renderLegend();
      this.render();
    }

    _renderLegend() {
      if (!this.data || !this.data.legendEl) return;
      const el = this.data.legendEl;
      el.innerHTML = '';
      if (this.data.series.length < 2) return;
      this.data.series.forEach((s) => {
        const chip = document.createElement('span');
        chip.className = 'legend-chip';
        chip.innerHTML = `<i style="background:${s.color}"></i>${s.name}`;
        el.appendChild(chip);
      });
    }

    _plotRect(w, h) {
      return { left: 52, right: 16, top: 14, bottom: 30, w: w - 68, h: h - 44 };
    }

    render() {
      if (!this.data) return;
      const { ctx, w, h } = setupCanvas(this.canvas);
      const p = this._plotRect(w, h);
      const { dates, series, refLines = [] } = this.data;
      const n = dates.length;
      if (n === 0) return;

      // y-domain
      let ymin, ymax;
      if (this.data.yDomain) {
        [ymin, ymax] = this.data.yDomain;
      } else {
        ymin = Infinity; ymax = -Infinity;
        for (const s of series) for (const v of s.values) if (v != null) { if (v < ymin) ymin = v; if (v > ymax) ymax = v; }
        if (!isFinite(ymin)) { ymin = 0; ymax = 1; }
        const pad = (ymax - ymin) * 0.08 || 0.5;
        ymin -= pad; ymax += pad;
      }
      const xAt = (i) => p.left + (n === 1 ? p.w / 2 : (i / (n - 1)) * p.w);
      const yAt = (v) => p.top + p.h - ((v - ymin) / (ymax - ymin)) * p.h;

      // gridlines + y labels
      const grid = cssVar('--grid');
      const muted = cssVar('--muted');
      ctx.font = "11px 'IBM Plex Mono', monospace";
      ctx.textBaseline = 'middle';
      const yFmt = this.data.yTickFormat || ((v) => v.toFixed(2));
      for (const t of niceTicks(ymin, ymax, 5)) {
        if (t < ymin || t > ymax) continue;
        const y = yAt(t);
        ctx.strokeStyle = grid; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(p.left, y + 0.5); ctx.lineTo(p.left + p.w, y + 0.5); ctx.stroke();
        ctx.fillStyle = muted; ctx.textAlign = 'right';
        ctx.fillText(yFmt(t), p.left - 8, y);
      }

      // reference lines (e.g. y=0, y=1)
      for (const r of refLines) {
        if (r.y < ymin || r.y > ymax) continue;
        const y = yAt(r.y);
        ctx.strokeStyle = cssVar('--axis'); ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(p.left, y + 0.5); ctx.lineTo(p.left + p.w, y + 0.5); ctx.stroke();
        ctx.setLineDash([]);
      }

      // x labels (~6)
      ctx.fillStyle = muted; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      const xTickCount = Math.min(6, n);
      for (let k = 0; k < xTickCount; k++) {
        const i = Math.round((k / (xTickCount - 1)) * (n - 1));
        ctx.fillText(formatMonth(dates[i]), xAt(i), p.top + p.h + 8);
      }

      // series
      ctx.lineWidth = 2; ctx.lineJoin = 'round';
      for (const s of series) {
        ctx.strokeStyle = s.color;
        ctx.beginPath();
        let pen = false;
        for (let i = 0; i < n; i++) {
          const v = s.values[i];
          if (v == null) { pen = false; continue; }
          const x = xAt(i), y = yAt(v);
          if (!pen) { ctx.moveTo(x, y); pen = true; } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // crosshair + hover markers
      if (this.hover != null) {
        const i = this.hover;
        const x = xAt(i);
        ctx.strokeStyle = cssVar('--axis'); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x + 0.5, p.top); ctx.lineTo(x + 0.5, p.top + p.h); ctx.stroke();
        for (const s of series) {
          const v = s.values[i];
          if (v == null) continue;
          ctx.fillStyle = s.color;
          ctx.beginPath(); ctx.arc(x, yAt(v), 3.5, 0, Math.PI * 2); ctx.fill();
          ctx.fillStyle = cssVar('--surface');
          ctx.beginPath(); ctx.arc(x, yAt(v), 1.4, 0, Math.PI * 2); ctx.fill();
        }
      }

      this._p = p; this._n = n; this._xAt = xAt;
    }

    _move(e) {
      if (!this.data || !this._p) return;
      const rect = this.canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const p = this._p, n = this._n;
      let i = Math.round(((cx - p.left) / p.w) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      this.hover = i;
      this.render();

      const fmt = this.data.format || ((v) => v.toFixed(2));
      let html = `<div class="tt-date">${this.data.dates[i]}</div>`;
      for (const s of this.data.series) {
        const v = s.values[i];
        html += `<div class="tt-row"><span><i style="background:${s.color}"></i>${s.name}</span><b>${v == null ? '—' : fmt(v)}</b></div>`;
      }
      this.tooltip.innerHTML = html;
      this.tooltip.style.display = 'block';
      const tw = this.tooltip.offsetWidth;
      const x = this._xAt(i);
      const left = x + 14 + tw > rect.width ? x - 14 - tw : x + 14;
      this.tooltip.style.left = `${Math.max(4, left)}px`;
      this.tooltip.style.top = `${p.top + 4}px`;
    }

    destroy() { this._ro.disconnect(); }
  }

  // -------------------------------------------------------------------- Heatmap
  class Heatmap {
    constructor(container) {
      this.container = container;
      this.canvas = document.createElement('canvas');
      this.canvas.className = 'chart-canvas';
      this.tooltip = document.createElement('div');
      this.tooltip.className = 'chart-tooltip';
      this.tooltip.style.display = 'none';
      container.appendChild(this.canvas);
      container.appendChild(this.tooltip);
      this.data = null;
      this.hoverCell = null;

      this.canvas.addEventListener('mousemove', (e) => this._move(e));
      this.canvas.addEventListener('mouseleave', () => { this.hoverCell = null; this.tooltip.style.display = 'none'; this.render(); });
      this.canvas.addEventListener('click', () => {
        if (this.hoverCell && this.data.onSelect) this.data.onSelect(this.hoverCell.i, this.hoverCell.j);
      });
      this._ro = new ResizeObserver(() => this.render());
      this._ro.observe(container);
    }

    setData(data) { this.data = data; this.render(); }

    render() {
      if (!this.data) return;
      const { ctx, w, h } = setupCanvas(this.canvas);
      const { labels, matrix } = this.data;
      const nn = labels.length;
      const pad = { left: 78, top: 78, right: 14, bottom: 14 };
      const gridW = w - pad.left - pad.right;
      const gridH = h - pad.top - pad.bottom;
      const cell = Math.min(gridW, gridH) / nn;
      const color = makeDiverging();

      const cellX = (j) => pad.left + j * cell;
      const cellY = (i) => pad.top + i * cell;

      ctx.font = "10px 'IBM Plex Mono', monospace";
      // cells
      for (let i = 0; i < nn; i++) {
        for (let j = 0; j < nn; j++) {
          const v = matrix[i][j];
          ctx.fillStyle = color(v);
          ctx.fillRect(cellX(j), cellY(i), cell - 1, cell - 1);
        }
      }
      // hover highlight
      if (this.hoverCell) {
        const { i, j } = this.hoverCell;
        ctx.strokeStyle = cssVar('--accent'); ctx.lineWidth = 2;
        ctx.strokeRect(cellX(j) + 1, cellY(i) + 1, cell - 3, cell - 3);
      }
      // labels
      ctx.fillStyle = cssVar('--muted');
      ctx.textBaseline = 'middle';
      for (let i = 0; i < nn; i++) {
        ctx.textAlign = 'right';
        ctx.fillText(labels[i], pad.left - 8, cellY(i) + cell / 2);
      }
      ctx.save();
      for (let j = 0; j < nn; j++) {
        ctx.save();
        ctx.translate(cellX(j) + cell / 2, pad.top - 8);
        ctx.rotate(-Math.PI / 4);
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(labels[j], 0, 0);
        ctx.restore();
      }
      ctx.restore();

      this._geo = { pad, cell, nn };
    }

    _move(e) {
      if (!this.data || !this._geo) return;
      const rect = this.canvas.getBoundingClientRect();
      const { pad, cell, nn } = this._geo;
      const j = Math.floor((e.clientX - rect.left - pad.left) / cell);
      const i = Math.floor((e.clientY - rect.top - pad.top) / cell);
      if (i < 0 || j < 0 || i >= nn || j >= nn) {
        this.hoverCell = null; this.tooltip.style.display = 'none'; this.render(); return;
      }
      this.hoverCell = { i, j };
      this.render();
      const v = this.data.matrix[i][j];
      this.tooltip.innerHTML =
        `<div class="tt-row"><span>${this.data.labels[i]} · ${this.data.labels[j]}</span></div>` +
        `<div class="tt-big" style="color:${makeDiverging()(v)}">${v == null ? '—' : v.toFixed(2)}</div>`;
      this.tooltip.style.display = 'block';
      const tw = this.tooltip.offsetWidth;
      const cx = pad.left + j * cell + cell;
      this.tooltip.style.left = `${Math.min(rect.width - tw - 4, cx + 8)}px`;
      this.tooltip.style.top = `${pad.top + i * cell}px`;
    }

    destroy() { this._ro.disconnect(); }
  }

  return { LineChart, Heatmap, makeDiverging };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = Charts;
