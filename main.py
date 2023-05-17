import yfinance as yf
import pandas as pd
import json
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.offline import plot
import os

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

# Function to plot cross correlation
def plot_correlation(data, assets, time_horizons):
    for i in range(len(assets)-1):
        for j in range(i+1, len(assets)):
            fig = go.Figure()
            for period in time_horizons:
                corr_data = cross_correlation(data, period)
                corr = corr_data[assets[i]].unstack()[assets[j]].dropna()
                fig.add_trace(go.Scatter(x=corr.index, y=corr,
                                         mode='lines',
                                         name=f'{period} days'))
            fig.update_layout(title=f'Cross Correlation of {assets[i]} vs {assets[j]}',
                              xaxis_title='Date',
                              yaxis_title='Correlation')
            file_name = f"html/{assets[i].replace('^', '_').replace('=', '_')}_vs_{assets[j].replace('^', '_').replace('=', '_')}_correlation.html"
            plot(fig, filename = file_name, auto_open=False)

# Define assets and display names
assets = ['BTC-USD', 'ETH-USD', '^IXIC', '^GSPC', 'GC=F', 'DX-Y.NYB', 'EURUSD=X']
display_names = ['BTC-USD', 'ETH-USD', 'NDAQ', 'SPY', 'GC=F', 'DX-Y.NYB', 'EURUSD=X']
time_horizons = [30, 60, 90, 180, 360, 1095]  # 3 years = 1095 days

# Save assets and display names to JSON
with open('json/assets.json', 'w') as file:
    json.dump(assets, file)
with open('json/display_names.json', 'w') as file:
    json.dump(display_names, file)

# Create a mapping from display names to ticker symbols
name_to_symbol = {display: actual for display, actual in zip(display_names, assets)}
with open('json/name_to_symbol.json', 'w') as file:
    json.dump(name_to_symbol, file)

# Download historical price data
start_date = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')  # 5 years
end_date = datetime.now().strftime('%Y-%m-%d')
data = download_data(assets, start_date, end_date)

# Calculate and plot cross correlation
plot_correlation(data, assets, time_horizons)
