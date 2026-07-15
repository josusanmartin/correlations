'use strict';

// ---------------------------------------------------------------------------
// State + config loading
// ---------------------------------------------------------------------------
let assets = {};        // ticker -> display name
let assetOrder = [];    // tickers in canonical (config) order
let timeHorizons = {};  // day-count key -> display name
let chartType = 'correlation';

const WATERMARK = {
  text: 'correlations.josusanmartin.com',
  xref: 'paper', yref: 'paper',
  x: 1, y: 0, xanchor: 'right', yanchor: 'bottom',
  showarrow: false,
  font: { size: 16, color: '#888' },
  opacity: 0.3,
};

const EXPLANATIONS = {
  correlation:
    '<b>Correlation</b><br>Rolling Pearson correlation between two assets. ' +
    'A value near 1 means they move together, near -1 means they move oppositely.',
  correlation1all:
    '<b>Correlation (1 vs All)</b><br>Rolling Pearson correlation of one asset against every other tracked asset.',
  beta:
    '<b>Beta</b><br>Sensitivity of an asset\'s returns to Bitcoin. ' +
    'Above 1 means more volatile than Bitcoin, below 1 means less volatile.',
  volatility:
    '<b>Volatility</b><br>Annualized standard deviation of daily returns — how much an asset\'s price swings.',
};

// Assets offered in the "1 vs All" view (must have generated *_correlations.json files).
const ONE_VS_ALL_ASSETS = ['BTC-USD', 'ETH-USD'];

Promise.all([
  fetch('config/assets.json').then((r) => r.json()),
  fetch('config/time_horizons.json').then((r) => r.json()),
]).then(([assetData, horizonData]) => {
  assets = assetData;
  assetOrder = Object.keys(assetData);
  timeHorizons = horizonData;
  populateDropdowns();
  setChartType('correlation');
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Canonical, order-independent filename for a pair (matches the generator).
function pairFile(a, b) {
  const [first, second] = [a, b].sort(
    (x, y) => assetOrder.indexOf(x) - assetOrder.indexOf(y)
  );
  return `data/${first}_vs_${second}.json`;
}

function fetchJSON(url) {
  return fetch(url).then((r) => {
    if (!r.ok) throw new Error(`${url} not found`);
    return r.json();
  });
}

function render(traces, title, yTitle) {
  Plotly.newPlot(
    'mainChart',
    traces,
    {
      title,
      xaxis: { title: 'Date' },
      yaxis: { title: yTitle },
      margin: { t: 60 },
      showlegend: traces.length > 1,
      legend: { x: 1, xanchor: 'right', y: 1 },
      annotations: [WATERMARK],
    },
    { responsive: true }
  );
}

function fillSelect(el, entries, valueOf, labelOf) {
  el.innerHTML = '';
  entries.forEach((item) => el.options.add(new Option(labelOf(item), valueOf(item))));
}

function populateDropdowns() {
  const tickers = assetOrder;
  const horizonKeys = Object.keys(timeHorizons);
  const ticker = (t) => t;
  const tickerLabel = (t) => assets[t];
  const horizonLabel = (k) => timeHorizons[k];

  fillSelect(document.getElementById('asset1'), tickers, ticker, tickerLabel);
  fillSelect(document.getElementById('asset2'), tickers, ticker, tickerLabel);
  document.getElementById('asset2').selectedIndex = 1;

  fillSelect(
    document.getElementById('betaAsset'),
    tickers.filter((t) => t !== 'BTC-USD'),
    ticker,
    tickerLabel
  );

  ['corrTimeHorizon', 'oneAllTimeHorizon', 'betaTimeHorizon', 'volTimeHorizon'].forEach((id) =>
    fillSelect(document.getElementById(id), horizonKeys, (k) => k, horizonLabel)
  );

  buildVolatilityCheckboxes();
}

function buildVolatilityCheckboxes() {
  const container = document.getElementById('volatilityAssetCheckboxes');
  container.innerHTML = '';
  assetOrder.forEach((tickerKey) => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = tickerKey;
    checkbox.checked = tickerKey === 'BTC-USD' || tickerKey === 'ETH-USD';
    checkbox.addEventListener('change', updateMainChart);
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(assets[tickerKey]));
    container.appendChild(label);
  });
}

// ---------------------------------------------------------------------------
// Chart type switching
// ---------------------------------------------------------------------------
function setChartType(type) {
  chartType = type;
  document.getElementById('chartExplanation').innerHTML = EXPLANATIONS[type] || '';

  document.querySelectorAll('[data-controls]').forEach((el) => {
    el.hidden = el.dataset.controls !== type;
  });
  document.querySelectorAll('.chart-type-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.chart === type);
  });

  updateMainChart();
}

// ---------------------------------------------------------------------------
// Chart renderers
// ---------------------------------------------------------------------------
const renderers = {
  correlation() {
    const a = document.getElementById('asset1').value;
    const b = document.getElementById('asset2').value;
    const period = document.getElementById('corrTimeHorizon').value;
    if (!a || !b || a === b) return Promise.resolve(Plotly.purge('mainChart'));

    return fetchJSON(pairFile(a, b)).then((json) => {
      const series = json.correlations[timeHorizons[period]];
      render(
        [{ x: series.dates, y: series.correlation, mode: 'lines',
           line: { color: '#c0392b', width: 2 }, name: `Correlation (${timeHorizons[period]})` }],
        `Rolling Correlation: ${assets[a]} vs ${assets[b]} (${timeHorizons[period]})`,
        'Correlation'
      );
    });
  },

  correlation1all() {
    const asset = document.getElementById('oneAllAsset').value;
    const period = document.getElementById('oneAllTimeHorizon').value;
    if (!asset || !period) return Promise.resolve(Plotly.purge('mainChart'));

    return fetchJSON(`data/${asset}_${period}_correlations.json`).then((json) => {
      const traces = Object.entries(json.correlations).map(([other, series]) => ({
        x: series.dates, y: series.correlation, mode: 'lines', name: other,
      }));
      render(traces, `Correlation of ${assets[asset] || asset} with all assets (${timeHorizons[period]})`, 'Correlation');
    });
  },

  beta() {
    const asset = document.getElementById('betaAsset').value;
    const period = document.getElementById('betaTimeHorizon').value;
    if (!asset || !period) return Promise.resolve(Plotly.purge('mainChart'));

    return fetchJSON(`data/beta_BTC-USD_${period}.json`).then((json) => {
      const series = json[asset];
      if (!series) return Plotly.purge('mainChart');
      render(
        [{ x: series.dates, y: series.beta, mode: 'lines',
           line: { color: '#1f77b4', width: 2 }, name: 'Beta vs BTC-USD' }],
        `Rolling Beta of ${assets[asset]} with Bitcoin (${timeHorizons[period]})`,
        'Beta'
      );
    });
  },

  volatility() {
    const period = document.getElementById('volTimeHorizon').value;
    if (!period) return Promise.resolve(Plotly.purge('mainChart'));

    const selected = Array.from(
      document.querySelectorAll('#volatilityAssetCheckboxes input:checked')
    ).map((cb) => cb.value);

    return fetchJSON(`data/volatility_${period}.json`).then((json) => {
      const traces = selected
        .filter((ticker) => json[ticker])
        .map((ticker) => ({
          x: json[ticker].dates, y: json[ticker].volatility, mode: 'lines', name: assets[ticker],
        }));
      render(traces, `Rolling Volatility (${timeHorizons[period]})`, 'Annualized Volatility');
    });
  },
};

function updateMainChart() {
  const run = renderers[chartType];
  if (!run) return;
  Promise.resolve(run()).catch(() => Plotly.purge('mainChart'));
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
document.querySelectorAll('.chart-type-btn').forEach((btn) => {
  btn.addEventListener('click', () => setChartType(btn.dataset.chart));
});
document.querySelectorAll('[data-action="update"]').forEach((btn) => {
  btn.addEventListener('click', updateMainChart);
});
document.getElementById('volTimeHorizon').addEventListener('change', updateMainChart);
