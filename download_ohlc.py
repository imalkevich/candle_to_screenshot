import argparse
from datetime import datetime, timedelta
import pandas as pd
import requests
from pathlib import Path
import re
from typing import Literal

try:
    import yfinance as yf  # For forex / equities
except ImportError:  # allow crypto-only usage without yfinance installed
    yf = None

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

def download_ohlc(symbol: str, interval: str, time_interval: str, source: Literal['binance','forex']='binance'):
    """Download OHLC data either from Binance (crypto) or via yfinance (forex / equities).

    For forex mode we map symbol like GBPUSD -> GBPUSD=X (Yahoo Finance) unless user already
    provides a trailing =X or another valid ticker.
    Returns a DataFrame with at least: open_time, open, high, low, close, volume, close_time.
    Volume for forex is synthetic (set to 0) because free Yahoo FX feed does not supply tick volume
    comparable to crypto trade volume.
    """
    if interval not in INTERVALS:
        raise ValueError(f"Interval {interval} not supported.")

    if source == 'binance':
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
            'limit': 1000
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

    # Forex via yfinance
    if source == 'forex':
        if yf is None:
            raise RuntimeError("yfinance not installed. Please add yfinance to requirements and reinstall.")
        # Map interval to yfinance valid interval strings
        yf_interval = interval
        if yf_interval == '1M':  # yfinance uses 1mo
            yf_interval = '1mo'
        end_time = datetime.utcnow()
        start_time = end_time - parse_time_interval(time_interval)
        # Symbol normalization (e.g. GBPUSD -> GBPUSD=X)
        yf_symbol = symbol
        if not yf_symbol.endswith('=X') and len(yf_symbol) == 6:
            yf_symbol = yf_symbol.upper() + '=X'
        data = yf.download(
            yf_symbol,
            start=start_time,
            end=end_time,
            interval=yf_interval,
            progress=False,
            auto_adjust=False,
            prepost=False
        )
        if data.empty:
            raise ValueError(f"No data returned for {yf_symbol} interval={interval} range={time_interval}")
        # Flatten multi-index columns if present (can occur for some tickers)
        if isinstance(data.columns, pd.MultiIndex):
            # Typical shape: (PriceLevel, Ticker) -> we want just PriceLevel lowercased
            try:
                data.columns = [c[0].lower() if isinstance(c, tuple) and len(c) > 0 else str(c).lower() for c in data.columns]
            except Exception:
                data.columns = ["_".join([str(x) for x in c]).lower() if isinstance(c, tuple) else str(c).lower() for c in data.columns]
        else:
            # Single-level columns, standard rename
            rename_map = {'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}
            data = data.rename(columns=rename_map)
        if 'volume' not in data.columns:
            data['volume'] = 0
        data.index = pd.to_datetime(data.index)

        def interval_to_delta(iv: str):
            if iv.endswith('m'):
                return timedelta(minutes=int(iv[:-1]))
            if iv.endswith('h'):
                return timedelta(hours=int(iv[:-1]))
            if iv.endswith('d'):
                return timedelta(days=int(iv[:-1]))
            if iv.endswith('w'):
                return timedelta(weeks=int(iv[:-1]))
            if iv in ('1M', '1mo'):
                return timedelta(days=30)
            return timedelta(0)

        delta = interval_to_delta(yf_interval)

        # Build output incrementally to avoid 2D array surprises
        out = data[['open', 'high', 'low', 'close']].copy()
        out['volume'] = data['volume'].fillna(0).astype(float)
        out.insert(0, 'open_time', out.index)
        out['close_time'] = out['open_time'] + delta
        out['quote_asset_volume'] = 0
        out['number_of_trades'] = 0
        out['taker_buy_base_asset_volume'] = 0
        out['taker_buy_quote_asset_volume'] = 0
        out['ignore'] = 0
        # Round OHLC values to 4 decimal places for forex consistency
        out[['open','high','low','close']] = out[['open','high','low','close']].astype(float).round(4)
        out = out[['open_time','open','high','low','close','volume','close_time','quote_asset_volume','number_of_trades','taker_buy_base_asset_volume','taker_buy_quote_asset_volume','ignore']]
        return out

    raise ValueError(f"Unknown source: {source}")

def main():
    parser = argparse.ArgumentParser(description='Download OHLC data for a ticker (crypto via Binance or forex via Yahoo Finance).')
    parser.add_argument('--ticker', required=True, help='Ticker symbol, e.g. BTCUSDT')
    parser.add_argument('--interval', required=True, help='Chart interval, e.g. 15m')
    parser.add_argument('--time', required=True, help='Time interval, e.g. "1 month" or "1 year"')
    parser.add_argument('--source', choices=['binance','forex'], default='binance', help='Data source: binance (crypto) or forex (Yahoo Finance).')
    args = parser.parse_args()

    df = download_ohlc(args.ticker, args.interval, args.time, source=args.source)

    # Sanitize time string for filename (e.g. "1 month" -> "1month")
    sanitized_time = re.sub(r'\s+', '', args.time.lower())
    suffix = 'fx' if args.source == 'forex' else 'spot'
    filename = f"{args.ticker.upper()}_{args.interval}_{sanitized_time}_{suffix}.csv"
    data_dir = Path('data')
    data_dir.mkdir(parents=True, exist_ok=True)
    output_path = data_dir / filename
    df.to_csv(output_path, index=False)
    print(f"Saved OHLC data to {output_path}")

if __name__ == "__main__":
    main()
