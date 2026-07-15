# Correlate

An asset-correlation terminal: rolling **correlation**, **beta** and
**volatility** between Bitcoin, Ethereum and traditional assets — plus a full
**correlation matrix** of every pair at a glance.

Live site: <https://correlations.josusanmartin.com>

## The idea: ship prices once, compute in the browser

The whole app runs off **one small file** — five years of daily closing prices
(`public/data/prices.json`, ~230 KB). Every metric is derived client-side from
those prices:

```
prices ──► daily returns ──► rolling correlation / beta / volatility / matrix
```

That single decision is what makes this leaner, faster and more capable than the
old design, which pre-computed **214 JSON files (~600 MB)** on a server and
fetched one per interaction:

| | Old | New |
|---|---|---|
| Data files | 214 (~600 MB) | 1 (~230 KB) |
| Per-interaction network | fetch a file each time | none — instant |
| Charting | Plotly (~3.5 MB CDN) | custom canvas, no deps |
| Window sizes | 6 fixed presets | any window, via a slider |
| Correlation matrix | not possible | the flagship view |
| Git history growth | ~0.5 GB/day (committed data) | none |

## Views

- **Matrix** — correlation heatmap of all assets over the chosen window; click a
  cell to drill into that pair.
- **Pair** — rolling correlation between any two assets.
- **1 vs All** — one asset against every other, each line coloured by its current
  correlation.
- **Beta** — rolling beta of an asset against a selectable base (Bitcoin default).
- **Volatility** — annualized volatility of any set of assets.

State lives in the URL hash, so any view is shareable.

## Layout

```
public/                 # the published site (Pages artifact root)
  index.html            # markup only
  css/app.css           # design system (both themes)
  js/metrics.js         # returns + rolling correlation/beta/volatility/matrix
  js/charts.js          # canvas LineChart + Heatmap (no libraries)
  js/app.js             # views, controls, hash routing, theming
  config/assets.json    # ticker -> display name (generator input)
  data/prices.json      # GENERATED, git-ignored
  CNAME
generate.py             # download prices -> public/data/prices.json
tools/check-no-data.sh  # guard: fails if data/large blobs get tracked
.github/workflows/deploy.yml
```

## Why the repo used to be ~20 GB — and won't be again

The old workflow ran `git add .` on ~600 MB of regenerated JSON and force-pushed
it **every day**, burying ~0.5 GB of blobs in history per run. Now:

1. `public/data/` is **git-ignored** — generated data is never a source file.
2. CI regenerates it and publishes it **straight to GitHub Pages as a deployment
   artifact** (`upload-pages-artifact` → `deploy-pages`), so nothing large ever
   enters git.
3. `tools/check-no-data.sh` runs in CI (and can be a local pre-commit hook) and
   **fails the build** if any data file or >1 MB blob is ever tracked.

Enable the guard locally:

```bash
git config core.hooksPath tools/hooks
```

## Local development

```bash
pip install -r requirements.txt
python generate.py                 # writes public/data/prices.json (needs network)
python -m http.server -d public 8000
# open http://localhost:8000
```

Add or rename assets by editing `public/config/assets.json` — the generator and
the frontend both read it; no code changes needed.

## Methodology

Prices are adjusted closes aligned to a shared **business-day** calendar over the
last five years, so crypto and equities are compared on the same trading days.
Windows are measured in **trading days**. Correlation is the Pearson coefficient
of daily returns over the rolling window; beta is `cov(asset, base)/var(base)`;
volatility is the sample standard deviation of daily returns, annualized by
√252. These match a pandas reference implementation to ~1e-15.

## One-time cleanup of the bloated remote

The refactor stops *new* bloat, but the existing 20 GB is still in remote
history. Since all of it is regenerable data, replace the history with a single
clean commit:

```bash
git checkout --orphan clean
git add -A
git commit -m "Refactor: prices-only data, in-browser metrics, Pages deploy"
git branch -D main && git branch -m main
git push -f origin main
```

Then in **Settings → Pages**, set the source to **GitHub Actions**.

## License

[MIT](https://choosealicense.com/licenses/mit/)
