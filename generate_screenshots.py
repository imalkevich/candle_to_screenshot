import argparse
from pathlib import Path
import pandas as pd
import mplfinance as mpf
import re
import shutil
from download_ohlc import download_ohlc  # direct function import

DATA_DIR = Path('data')
SCREENSHOTS_DIR = Path('screenshots')


def build_data_filename(ticker: str, interval: str, time_range: str) -> Path:
    sanitized_time = re.sub(r'\s+', '', time_range.lower())
    filename = f"{ticker.upper()}_{interval}_{sanitized_time}.csv"
    return DATA_DIR / filename


def ensure_data(ticker: str, interval: str, time_range: str, refresh: bool) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = build_data_filename(ticker, interval, time_range)
    if refresh or not csv_path.exists():
        print(f"[INFO] Fetching data directly via function call: {ticker} {interval} {time_range}")
        df = download_ohlc(ticker, interval, time_range)
        df.to_csv(csv_path, index=False)
    else:
        print(f"[INFO] Using existing data file: {csv_path}")
    return csv_path


def load_dataframe(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # Expect columns open_time, open, high, low, close, volume, ...
    if 'open_time' not in df.columns:
        raise ValueError("CSV missing 'open_time' column.")
    df['open_time'] = pd.to_datetime(df['open_time'])
    df = df.set_index('open_time')
    # Rename to match typical OHLC naming expected by mplfinance
    rename_map = {
        'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'
    }
    df = df.rename(columns=rename_map)
    required = ['Open', 'High', 'Low', 'Close']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Column '{col}' missing in data file.")
    return df


def generate_screenshots(df: pd.DataFrame, ticker: str, interval: str, time_range: str, start_skip: int = 480, max_candles: int = 96):
    sanitized_time = re.sub(r'\s+', '', time_range.lower())
    base_folder = SCREENSHOTS_DIR / f"{ticker.upper()}_{interval}_{sanitized_time}"
    # Clean existing folder to avoid stale images influencing downstream ML processes
    if base_folder.exists():
        try:
            shutil.rmtree(base_folder)
            print(f"[INFO] Cleaned existing folder: {base_folder}")
        except Exception as e:
            print(f"[WARN] Could not fully remove existing folder '{base_folder}': {e}")
    base_folder.mkdir(parents=True, exist_ok=True)
    total = len(df)
    if total <= start_skip:
        print(f"[WARN] Not enough candles ({total}) to start after skip={start_skip}. No screenshots created.")
        return
    print(f"[INFO] Generating {total - start_skip} screenshots (skipping first {start_skip} of {total} candles)...")
    # Iterate from start_skip+1 to total inclusive to include each new candle
    for i in range(start_skip + 1, total + 1):
        # Determine subset up to i, but capped to last max_candles candles
        window_start = max(0, i - max_candles)
        subset = df.iloc[window_start:i]
        out_file = base_folder / f"candle_{i:05d}.png"
        if out_file.exists():
            # Skip if already exists (idempotency)
            continue
        # Create the candlestick plot but suppress axes for ML friendliness
        fig, axlist = mpf.plot(
            subset,
            type='candle',
            style='charles',
            returnfig=True,
            axisoff=True,
        )
        # axisoff removes axes but ensure no leftover padding or labels
        for ax in (axlist if isinstance(axlist, (list, tuple)) else [axlist]):
            ax.set_axis_off()
        fig.savefig(out_file, bbox_inches='tight', pad_inches=0)
        # Explicitly close to free memory when generating many images
        import matplotlib.pyplot as plt  # local import to avoid overhead if not used elsewhere
        plt.close(fig)
        if i % 100 == 0 or i == total:
            print(f"[INFO] Saved {i - start_skip}/{total - start_skip} -> {out_file}")
    print(f"[DONE] Screenshots saved under {base_folder}")


def main():
    parser = argparse.ArgumentParser(description='Generate sequential candlestick screenshots from OHLC data.')
    parser.add_argument('--ticker', required=True, help='Ticker symbol, e.g. BTCUSDT')
    parser.add_argument('--interval', required=True, help='Chart interval, e.g. 15m')
    parser.add_argument('--time', required=True, help='Time interval, e.g. "1 month" or "1 year"')
    parser.add_argument('--refresh', action='store_true', help='Re-fetch data even if CSV already exists')
    parser.add_argument('--skip', type=int, default=480, help='Number of initial candles to skip for screenshot generation (default 480)')
    parser.add_argument('--max-candles', type=int, default=96, dest='max_candles', help='Maximum number of most recent candles to display in each screenshot window (default 96 = 1 day of 15m candles)')
    args = parser.parse_args()

    csv_path = ensure_data(args.ticker, args.interval, args.time, args.refresh)
    df = load_dataframe(csv_path)
    generate_screenshots(df, args.ticker, args.interval, args.time, start_skip=args.skip, max_candles=args.max_candles)


if __name__ == '__main__':
    main()
