# Asset Correlation Tracker

Visualise the historical relationship between crypto and traditional assets:
rolling **correlation** (pairwise and one-vs-all), **beta** vs Bitcoin, and
**volatility** — over rolling horizons of 30, 60, 90, 180 days, 1 year and 3
years, based on ~5 years of daily closing prices.

Live site: <https://correlations.josusanmartin.com>

## Architecture

This is a static site whose data is a **build artifact**, not source.

```
public/                 # the entire published site (Pages artifact root)
  index.html            # markup only
  css/app.css           # styles
  js/app.js             # all frontend logic (Plotly charts)
  config/               # asset list + time horizons (source of truth)
  data/                 # GENERATED, git-ignored, produced by generate.py
  CNAME
generate.py             # downloads prices → writes public/data/*.json
requirements.txt
.github/workflows/deploy.yml
```

**Why the repo used to be ~20 GB, and why it no longer is:** the old workflow ran
`git add .` on ~600 regenerated MB of JSON and force-pushed it **every day**, so
every run buried another ~0.5 GB of blobs in git history. Now the data is never
committed — the CI job regenerates it and publishes it straight to GitHub Pages
as a deployment artifact (`actions/upload-pages-artifact` → `deploy-pages`). Git
history stays tiny forever.

## Data contract

`generate.py` writes exactly the files `js/app.js` fetches:

| View                | File                                      | Shape |
|---------------------|-------------------------------------------|-------|
| Correlation (pair)  | `data/{a}_vs_{b}.json`                     | `{correlations: {"<horizon>": {dates, correlation}}}` |
| Correlation (1→all) | `data/{asset}_{days}_correlations.json`   | `{asset, period, correlations: {"<name>": {dates, correlation}}}` |
| Beta vs BTC         | `data/beta_BTC-USD_{days}.json`           | `{"<ticker>": {dates, beta}}` |
| Volatility          | `data/volatility_{days}.json`             | `{"<ticker>": {dates, volatility}}` |

Pair filenames are canonical (assets ordered by their position in
`config/assets.json`); the frontend sorts the same way, so either dropdown order
resolves to the same file.

## Local development

```bash
pip install -r requirements.txt
python generate.py          # writes public/data/ (needs network for yfinance)
python -m http.server -d public 8000
# open http://localhost:8000
```

To add or rename assets, edit `public/config/assets.json`; to change horizons,
edit `public/config/time_horizons.json`. Both the generator and frontend read
these, so no code changes are needed.

## One-time cleanup of the bloated remote

The refactor stops *new* bloat, but the existing 20 GB is still in remote
history. Because all of it is regenerable data, the history has no value —
replace it with a single clean commit:

```bash
# from a fresh checkout of this refactored tree
git checkout --orphan clean
git add -A
git commit -m "Refactor: data as build artifact, deploy via Pages"
git branch -D main
git branch -m main
git push -f origin main
git gc --aggressive --prune=now   # optional: shrink your local copy
```

After pushing, in the repo's **Settings → Pages**, set the source to
**GitHub Actions** (not "Deploy from a branch").

## License

[MIT](https://choosealicense.com/licenses/mit/)
