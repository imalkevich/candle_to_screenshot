import argparse
from datetime import datetime, timedelta
import pandas as pd
import requests
from pathlib import Path
import re

# Example: Download OHLC data from Binance
BINANCE_BASE_URL = "https://api.binance.com/api/v3/klines"

INTERVALS = {
    '1m': '1m',
    '3m': '3m',
    '5m': '5m',
    '15m': '15m',
    '30m': '30m',
    '1h': '1h',
    '2h': '2h',
    '4h': '4h',
    '6h': '6h',
    '8h': '8h',
    '12h': '12h',
    '1d': '1d',
    '3d': '3d',
    '1w': '1w',
    '1M': '1M',
}

def parse_time_interval(interval_str):
    # Accepts things like '1 month', '1 year', '3 days', etc.
    num, unit = interval_str.split()
    num = int(num)
    unit = unit.lower()
    if unit.startswith('month'):
        return timedelta(days=30 * num)
    elif unit.startswith('year'):
        return timedelta(days=365 * num)
    elif unit.startswith('day'):
        return timedelta(days=num)
    elif unit.startswith('hour'):
        return timedelta(hours=num)
    elif unit.startswith('min'):
        return timedelta(minutes=num)
    else:
        raise ValueError(f"Unknown time unit: {unit}")

def download_ohlc(symbol, interval, time_interval):
    if interval not in INTERVALS:
        raise ValueError(f"Interval {interval} not supported.")
    end_time = datetime.utcnow()
    start_time = end_time - parse_time_interval(time_interval)
    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    url = BINANCE_BASE_URL
    params = {
        'symbol': symbol.upper(),
        'interval': interval,
        'startTime': start_ms,
        'endTime': end_ms,
        'limit': 1000  # Binance max per request
    }
    all_data = []
    while True:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        all_data.extend(data)
        if len(data) < params['limit']:
            break
        params['startTime'] = data[-1][0] + 1
    df = pd.DataFrame(all_data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
    return df

def main():
    parser = argparse.ArgumentParser(description='Download OHLC data for a ticker.')
    parser.add_argument('--ticker', required=True, help='Ticker symbol, e.g. BTCUSDT')
    parser.add_argument('--interval', required=True, help='Chart interval, e.g. 15m')
    parser.add_argument('--time', required=True, help='Time interval, e.g. "1 month" or "1 year"')
    args = parser.parse_args()

    df = download_ohlc(args.ticker, args.interval, args.time)

    # Sanitize time string for filename (e.g. "1 month" -> "1month")
    sanitized_time = re.sub(r'\s+', '', args.time.lower())
    filename = f"{args.ticker.upper()}_{args.interval}_{sanitized_time}.csv"
    data_dir = Path('data')
    data_dir.mkdir(parents=True, exist_ok=True)
    output_path = data_dir / filename
    df.to_csv(output_path, index=False)
    print(f"Saved OHLC data to {output_path}")

if __name__ == "__main__":
    main()
