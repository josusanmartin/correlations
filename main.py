import yfinance as yf
import pandas as pd
import json
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.offline import plot
import os

# Define assets: ticker and display name.
assets = {
    "BTC-USD": "BTCUSD",
    "ETH-USD": "ETHUSD",
    "^IXIC": "NASDAQ",
    "^GSPC": "S&P",
    "GC=F": "GOLD",
    "DX-Y.NYB": "DXY",
    "EURUSD=X": "EURUSD",
    "NVDA": "NVIDIA",
    "TSLA": "TESLA",
    "BRK-B": "BERKSHIRE",
    "GME": "GAMESTOP",
    "GOOG": "ALPHABET",
    "AMZN": "AMAZON",
    "AAPL": "APPLE",
    "MSFT": "MICROSOFT",
    "META": "META",
    "NFLX": "NETFLIX",
}

# Define time horizons for the correlation. Number of days, and display name.
time_horizons = {
    30: '30 days',
    60: '60 days',
    90: '90 days',
    180: '180 days',
    360: '1 year',
    1095: '3 years'
}

# Create folders if they don't exist
if not os.path.exists('html'):
    os.makedirs('html')

if not os.path.exists('json'):
    os.makedirs('json')

# Function to download historical price data
def download_data(tickers, start_date, end_date):
    data = yf.download(tickers, start=start_date, end=end_date)['Close']
    return data

# Function to calculate cross correlation
def cross_correlation(data, period):
    return data.pct_change().rolling(window=period).corr().dropna()

def plot_correlation(data, assets, time_horizons):

    time_keys = list(time_horizons.keys())
    asset_keys = list(assets.keys())
    for i in range(len(asset_keys)-1):
        for j in range(i+1, len(asset_keys)):
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=('Correlation', 'Price'),
                                specs=[[{}], [{"secondary_y": True}]], row_heights=[0.67, 0.33], vertical_spacing=0.05)

            for period in time_keys:
                corr_data = cross_correlation(data, period)
                corr = corr_data[asset_keys[i]].unstack()[asset_keys[j]].dropna()
                fig.add_trace(go.Scatter(x=corr.index, y=corr,
                                         mode='lines',
                                         name=f'{time_horizons[period]}',
                                         showlegend=True), row=1, col=1)

            fig.add_trace(go.Scatter(x=data.index, y=data[asset_keys[i]],
                                     mode='lines',
                                     name=f'{assets[asset_keys[i]]} Price',
                                     showlegend=True), row=2, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data[asset_keys[j]],
                                     mode='lines',
                                     name=f'{assets[asset_keys[j]]} Price',
                                     showlegend=True), row=2, col=1, secondary_y=True)
            
            fig.update_yaxes(title_text=f"{assets[asset_keys[i]]} Price", tickformat=",.0f",row=2, col=1)
            fig.update_yaxes(title_text=f"{assets[asset_keys[j]]}", tickformat=",.0f",row=2, col=1, secondary_y=True)

            fig.update_layout(title=f'Cross Correlation of {assets[asset_keys[i]]} vs {assets[asset_keys[j]]}',
                              xaxis_title='Date',
                              yaxis_title='Correlation',
                              yaxis2_title=f'{assets[asset_keys[i]]}')
        
            file_name = f"html/{assets[asset_keys[i]]}_vs_{assets[asset_keys[j]]}_correlation.html"
            plot(fig, filename = file_name, auto_open=False)

def all_plot_correlation(data, assets, time_horizons):

    time_keys = list(time_horizons.keys())
    asset_keys = list(assets.keys())
    
    # Only run for the first two assets
    for asset in asset_keys[:2]:
        for period in time_keys:
            fig = go.Figure()
            for other_asset in asset_keys:
                if asset != other_asset:
                    corr_data = cross_correlation(data, period)
                    corr = corr_data[asset].unstack()[other_asset].dropna()
                    fig.add_trace(go.Scatter(x=corr.index, y=corr,
                                             mode='lines',
                                             name=assets[other_asset]))
            print(time_horizons[period])
            fig.update_layout(title=f'Cross Correlation of {assets[asset]} for {time_horizons[period]}',
                              xaxis_title='Date',
                              yaxis_title='Correlation')
            file_name = f"html/{assets[asset]}_{period}_correlation.html"
            plot(fig, filename = file_name, auto_open=False)



# Save assets and display names to JSON
with open('json/assets.json', 'w') as file:
    json.dump(assets, file)

# Save time horizons to JSON
with open('json/time_horizons.json', 'w') as file:
    json.dump(time_horizons, file)

# Download historical price data
start_date = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')  # 10 years
end_date = datetime.now().strftime('%Y-%m-%d')
data = download_data(list(assets.keys()), start_date, end_date)

# Calculate and plot cross correlation
plot_correlation(data, assets, time_horizons)
all_plot_correlation(data, assets, time_horizons)
