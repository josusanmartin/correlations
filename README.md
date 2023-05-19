# Asset Correlation Tracker

The Asset Correlation Tracker is a simple web application that allows users to visualize the historical correlation between different assets. The correlations are calculated over several rolling time horizons (30, 60, 90, 180, 360, 1095 days). The charts are based on daily closing prices over the past five years. 

## Getting Started

To get a local copy up and running, follow these steps:

1. Clone the repository to your local machine:

```
git clone https://github.com/your-username/asset-correlation-tracker.git
```

2. Navigate to the project directory:

```
cd asset-correlation-tracker
```

3. Install the required Python packages:

```
pip install yfinance pandas numpy plotly
```

4. Run the Python script to generate the correlation charts:

```
python correlation.py
```

5. Start a local HTTP server:

```
python -m http.server
```

6. Open your web browser and go to `http://localhost:8000`.

## Usage

Select two assets from the dropdown menus and click "Update Chart" to view their historical correlation. The chart will display the correlation over several rolling time horizons.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)
