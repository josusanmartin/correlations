import yfinance as yf
import pandas as pd
import json
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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

def plot_correlation(data, assets, time_horizons):
    time_horizons_names = {
        30: '30 days',
        60: '60 days',
        90: '90 days',
        180: '180 days',
        360: '1 year',
        1095: '3 years'
    }
    for i in range(len(assets)-1):
        for j in range(i+1, len(assets)):
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, subplot_titles=('Correlation', 'Price'),
                                specs=[[{}], [{"secondary_y": True}]], row_heights=[0.67, 0.33], vertical_spacing=0.05)

            for period in time_horizons:
                corr_data = cross_correlation(data, period)
                corr = corr_data[assets[i]].unstack()[assets[j]].dropna()
                fig.add_trace(go.Scatter(x=corr.index, y=corr,
                                         mode='lines',
                                         name=f'{time_horizons_names[period]}',
                                         showlegend=True), row=1, col=1)

            fig.add_trace(go.Scatter(x=data.index, y=data[assets[i]],
                                     mode='lines',
                                     name=f'{legend_names[assets[i]]} Price',
                                     showlegend=True), row=2, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data[assets[j]],
                                     mode='lines',
                                     name=f'{legend_names[assets[j]]} Price',
                                     showlegend=True), row=2, col=1, secondary_y=True)
            
            fig.update_yaxes(title_text=f"{legend_names[assets[i]]} Price", tickformat=",.0f",row=2, col=1)
            fig.update_yaxes(title_text=f"{legend_names[assets[j]]}", tickformat=",.0f",row=2, col=1, secondary_y=True)

            fig.update_layout(title=f'Cross Correlation of {legend_names[assets[i]]} vs {legend_names[assets[j]]}',
                              xaxis_title='Date',
                              yaxis_title='Correlation',
                              yaxis2_title=f'{legend_names[assets[i]]}')
                            #   legend=dict(orientation="h", yanchor="bottom", y=0.43, xanchor="right", x=0.8)
        
            file_name = f"html/{assets[i].replace('^', '_').replace('=', '_')}_vs_{assets[j].replace('^', '_').replace('=', '_')}_correlation.html"
            plot(fig, filename = file_name, auto_open=False)

# Function to plot cross correlation for all assets
def all_plot_correlation(data, assets, time_horizons, legend_names):
    # Mapping of time horizon in days to its equivalent in years
    time_horizons_names = {
        30: '30 days',
        60: '60 days',
        90: '90 days',
        180: '180 days',
        360: '1 year',
        1095: '3 years'
    }

    # Only run for the first two assets
    for asset in assets[:2]:
        for period in time_horizons:
            fig = go.Figure()
            for other_asset in assets:
                if asset != other_asset:
                    corr_data = cross_correlation(data, period)
                    corr = corr_data[asset].unstack()[other_asset].dropna()
                    fig.add_trace(go.Scatter(x=corr.index, y=corr,
                                             mode='lines',
                                             name=legend_names[other_asset]))
            print(time_horizons_names[period])
            fig.update_layout(title=f'Cross Correlation of {legend_names[asset]} for {time_horizons_names[period]}',
                              xaxis_title='Date',
                              yaxis_title='Correlation')
            file_name = f"html/{legend_names[asset]}_{period}_correlation.html"
            plot(fig, filename = file_name, auto_open=False)


# Define assets and display names
assets = ['BTC-USD', 'ETH-USD', '^IXIC', '^GSPC', 'GC=F', 'DX-Y.NYB', 'EURUSD=X']
legend_names = {
    "BTC-USD": "BTCUSD",
    "ETH-USD": "ETHUSD",
    "^IXIC": "NASDAQ",
    "^GSPC": "S&P",
    "GC=F": "GOLD",
    "DX-Y.NYB": "DXY",
    "EURUSD=X": "EURUSD"
}

# Define assets and display names
assets = ['BTC-USD', 'ETH-USD', '^IXIC', '^GSPC', 'GC=F', 'DX-Y.NYB', 'EURUSD=X']
display_names = ['BTC-USD', 'ETH-USD', 'NDAQ', 'SPY', 'GC=F', 'DX-Y.NYB', 'EURUSD=X']
time_horizons = [30, 60, 90, 180, 360, 1095]  # 3 years = 1095 days

# Save assets and display names to JSON
with open('json/assets.json', 'w') as file:
    json.dump(assets, file)
with open('json/display_names.json', 'w') as file:
    json.dump(display_names, file)

# Save time horizons to JSON
with open('json/time_horizons.json', 'w') as file:
    json.dump(time_horizons, file)

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
all_plot_correlation(data, assets, time_horizons, legend_names)