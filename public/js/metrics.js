/*
 * metrics.js — all the quantitative math, computed in the browser from raw prices.
 *
 * Everything derives from one aligned price matrix:
 *   returns  -> rolling correlation / beta / volatility / correlation matrix.
 *
 * Windows are measured in TRADING DAYS (observations), not calendar days, so
 * "90" means a 90-observation rolling window. Nulls (leading gaps before an
 * asset starts trading) propagate: a window containing any null yields null.
 *
 * Exposed as the global `Metrics` for browser <script> tags, and via
 * module.exports for Node tests.
 */
const Metrics = (() => {
  'use strict';

  const TRADING_DAYS = 252;

  /** Simple daily returns from a price array. r[0] is null. */
  function toReturns(prices) {
    const r = new Array(prices.length).fill(null);
    for (let i = 1; i < prices.length; i++) {
      const p0 = prices[i - 1];
      const p1 = prices[i];
      if (p0 != null && p1 != null && p0 !== 0) r[i] = p1 / p0 - 1;
    }
    return r;
  }

  /** Map ticker -> returns array, from ticker -> prices array. */
  function returnsByAsset(pricesByAsset) {
    const out = {};
    for (const t in pricesByAsset) out[t] = toReturns(pricesByAsset[t]);
    return out;
  }

  // --- Windowed accumulators over an aligned pair of return series ----------
  // Returns per-index sums so any rolling stat is O(n). Null in either series
  // marks that index invalid; a window is valid only if it has `window` valids.
  function pairPrefix(x, y) {
    const n = x.length;
    const cnt = new Float64Array(n + 1);
    const sx = new Float64Array(n + 1);
    const sy = new Float64Array(n + 1);
    const sxx = new Float64Array(n + 1);
    const syy = new Float64Array(n + 1);
    const sxy = new Float64Array(n + 1);
    for (let i = 0; i < n; i++) {
      const valid = x[i] != null && y[i] != null;
      const a = valid ? x[i] : 0;
      const b = valid ? y[i] : 0;
      cnt[i + 1] = cnt[i] + (valid ? 1 : 0);
      sx[i + 1] = sx[i] + a;
      sy[i + 1] = sy[i] + b;
      sxx[i + 1] = sxx[i] + a * a;
      syy[i + 1] = syy[i] + b * b;
      sxy[i + 1] = sxy[i] + a * b;
    }
    return { n, cnt, sx, sy, sxx, syy, sxy };
  }

  function windowSums(p, i, window) {
    const lo = i - window + 1;
    if (lo < 0) return null;
    const hi = i + 1;
    // Require a fully-valid window (no gaps).
    if (p.cnt[hi] - p.cnt[lo] !== window) return null;
    return {
      w: window,
      sx: p.sx[hi] - p.sx[lo],
      sy: p.sy[hi] - p.sy[lo],
      sxx: p.sxx[hi] - p.sxx[lo],
      syy: p.syy[hi] - p.syy[lo],
      sxy: p.sxy[hi] - p.sxy[lo],
    };
  }

  function pearsonFrom(s) {
    const covN = s.w * s.sxy - s.sx * s.sy;
    const varX = s.w * s.sxx - s.sx * s.sx;
    const varY = s.w * s.syy - s.sy * s.sy;
    const denom = Math.sqrt(varX * varY);
    if (denom === 0) return null;
    const r = covN / denom;
    return Math.max(-1, Math.min(1, r)); // clamp FP drift
  }

  /** Rolling Pearson correlation aligned to the input length (null where short). */
  function rollingCorrelation(x, y, window) {
    const p = pairPrefix(x, y);
    const out = new Array(p.n).fill(null);
    for (let i = window - 1; i < p.n; i++) {
      const s = windowSums(p, i, window);
      if (s) out[i] = pearsonFrom(s);
    }
    return out;
  }

  /** Rolling beta of `asset` returns vs `base` returns (cov/var, ddof cancels). */
  function rollingBeta(asset, base, window) {
    const p = pairPrefix(asset, base);
    const out = new Array(p.n).fill(null);
    for (let i = window - 1; i < p.n; i++) {
      const s = windowSums(p, i, window);
      if (!s) continue;
      const cov = s.w * s.sxy - s.sx * s.sy;
      const varBase = s.w * s.syy - s.sy * s.sy;
      if (varBase !== 0) out[i] = cov / varBase;
    }
    return out;
  }

  /** Rolling annualized volatility (sample std, ddof=1) of a return series. */
  function rollingVolatility(returns, window) {
    const p = pairPrefix(returns, returns);
    const out = new Array(p.n).fill(null);
    const scale = Math.sqrt(TRADING_DAYS);
    for (let i = window - 1; i < p.n; i++) {
      const s = windowSums(p, i, window);
      if (!s) continue;
      const variance = (s.sxx - (s.sx * s.sx) / s.w) / (s.w - 1);
      out[i] = Math.sqrt(Math.max(0, variance)) * scale;
    }
    return out;
  }

  /** Correlation over the most recent `window` observations between two series. */
  function latestCorrelation(x, y, window) {
    const p = pairPrefix(x, y);
    const s = windowSums(p, p.n - 1, window);
    return s ? pearsonFrom(s) : null;
  }

  /**
   * Full correlation matrix over the most recent `window` observations.
   * `tickers` sets the row/column order. Returns an NxN array (diagonal 1,
   * symmetric, null where a pair lacks a full recent window).
   */
  function correlationMatrix(returnsByTicker, tickers, window) {
    const n = tickers.length;
    const m = Array.from({ length: n }, () => new Array(n).fill(null));
    for (let i = 0; i < n; i++) {
      m[i][i] = 1;
      for (let j = i + 1; j < n; j++) {
        const r = latestCorrelation(returnsByTicker[tickers[i]], returnsByTicker[tickers[j]], window);
        m[i][j] = r;
        m[j][i] = r;
      }
    }
    return m;
  }

  /** Last non-null value of an array (for headline readouts). */
  function lastValue(arr) {
    for (let i = arr.length - 1; i >= 0; i--) if (arr[i] != null) return arr[i];
    return null;
  }

  return {
    TRADING_DAYS,
    toReturns,
    returnsByAsset,
    rollingCorrelation,
    rollingBeta,
    rollingVolatility,
    latestCorrelation,
    correlationMatrix,
    lastValue,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = Metrics;
