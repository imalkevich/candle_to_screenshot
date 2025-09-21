import argparse
from pathlib import Path
import re
import sys
import tkinter as tk
# ttk not needed here (no Treeview usage). Removed to avoid unused import warning.
from PIL import Image, ImageTk
from typing import List, Dict, Any, Optional, Tuple

# Reuse data utilities from existing generation module
from generate_screenshots import ensure_data, load_dataframe

# ---------------------------------------------------------------------------
# Helpers for locating processed folders
# ---------------------------------------------------------------------------
PROCESSED_DIR = Path('processed')


def processed_base(ticker: str, interval: str, time_range: str) -> Path:
    sanitized = re.sub(r'\s+', '', time_range.lower())
    return PROCESSED_DIR / f"{ticker.upper()}_{interval}_{sanitized}"


def build_processed_paths(ticker: str, interval: str, time_range: str):
    base = processed_base(ticker, interval, time_range)
    return {
        'base': base,
        'normal': base / 'normal',
        'buy': base / 'buy',
        'buy_exit': base / 'buy_exit',
        'sell': base / 'sell',
        'sell_exit': base / 'sell_exit'
    }


# ---------------------------------------------------------------------------
# Trade reconstruction (mirrors pairing logic in label_screenshots.py)
# ---------------------------------------------------------------------------

def _file_numeric(name: str) -> int:
    m = re.search(r'(\d+)', name)
    return int(m.group(1)) if m else 10**12


def reconstruct_trades(paths: Dict[str, Path]) -> List[Dict[str, Any]]:
    """Return list of CLOSED trades as dicts with:
        side, entry_file, exit_file, entry_num, exit_num
    Pair each entry with next chronological exit of same side.
    Skip entries that have no later exit (i.e., open trades).
    """
    buy_entries = sorted(paths['buy'].glob('candle_*.png'), key=lambda p: p.name)
    buy_exits = sorted(paths['buy_exit'].glob('candle_*.png'), key=lambda p: p.name)
    sell_entries = sorted(paths['sell'].glob('candle_*.png'), key=lambda p: p.name)
    sell_exits = sorted(paths['sell_exit'].glob('candle_*.png'), key=lambda p: p.name)

    def pair(entries: List[Path], exits: List[Path], side: str):
        results = []
        used = set()
        for e in entries:
            e_num = _file_numeric(e.name)
            chosen = None
            for x in exits:
                if x in used:
                    continue
                x_num = _file_numeric(x.name)
                if x_num > e_num:
                    chosen = x
                    used.add(x)
                    break
            if chosen is not None:
                results.append({
                    'side': side,
                    'entry_file': e,
                    'exit_file': chosen,
                    'entry_num': e_num,
                    'exit_num': _file_numeric(chosen.name)
                })
        return results

    trades = pair(buy_entries, buy_exits, 'BUY') + pair(sell_entries, sell_exits, 'SELL')
    # Sort chronologically by entry
    trades.sort(key=lambda t: t['entry_num'])
    return trades


# ---------------------------------------------------------------------------
# Candle / OHLC helpers (borrow logic style from label_screenshots.py)
# ---------------------------------------------------------------------------

def filename_to_index(filename: str, total_rows: int) -> Optional[int]:
    m = re.search(r'(\d+)', filename)
    if not m:
        return None
    idx = int(m.group(1)) - 1
    if 0 <= idx < total_rows:
        return idx
    return None


def extract_candle(df, idx: int) -> Optional[Tuple[Any, Any, Any, Any, Any, Any]]:
    try:
        if idx < 0 or idx >= len(df):
            return None
        row = df.iloc[idx]
        cols = df.columns
        if 'open_time' in cols:
            ts = row['open_time']
        elif 'close_time' in cols:
            ts = row['close_time']
        else:
            try:
                ts = df.index[idx]
            except Exception:
                ts = ''
        def pick(*names):
            for n in names:
                if n in row:
                    return row[n]
            return ''
        o = pick('Open', 'open')
        h = pick('High', 'high')
        low_v = pick('Low', 'low')
        c = pick('Close', 'close')
        v = pick('Volume', 'volume')
        return ts, o, h, low_v, c, v
    except Exception:
        return None


def close_price(df, idx: int) -> float:
    data = extract_candle(df, idx)
    if not data:
        return 0.0
    _, _o, _h, _l, c, _v = data
    try:
        return float(c)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Tkinter Application
# ---------------------------------------------------------------------------
class TradeViewerApp:
    def __init__(self, root, trades: List[Dict[str, Any]], df):
        self.root = root
        self.trades = trades
        self.df = df
        self.index = 0  # index into self.trades
        self.left_photo = None
        self.right_photo = None

        self.root.title('Trade Screenshot Checker')
        self.root.configure(bg='#222222')
        self.root.geometry('1320x700')
        try:
            self.root.minsize(1100, 660)
        except Exception:
            pass

        # Layout frames
        top_frame = tk.Frame(root, bg='#222222')
        top_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        images_frame = tk.Frame(top_frame, bg='#222222')
        images_frame.pack(fill=tk.BOTH, expand=True)

        self.left_label = tk.Label(images_frame, bg='#222222')
        self.left_label.pack(side=tk.LEFT, expand=True, padx=10)

        self.right_label = tk.Label(images_frame, bg='#222222')
        self.right_label.pack(side=tk.LEFT, expand=True, padx=10)

        details_frame = tk.Frame(top_frame, bg='#222222')
        details_frame.pack(fill=tk.X, pady=(6,4))

        self.status = tk.Label(details_frame, text='', bg='#222222', fg='#cccccc', font=('Arial', 11, 'bold'))
        self.status.pack(anchor='w', pady=(0,4))

        # Per-trade stats (single trade) similar styling to original stats panel
        stats_frame = tk.LabelFrame(top_frame, text='Trade Details', bg='#222222', fg='#dddddd', labelanchor='n', padx=8, pady=6)
        stats_frame.configure(highlightbackground='#444444', highlightcolor='#444444')
        stats_frame.pack(fill=tk.X, pady=(4,8))

        self.entry_file_label = tk.Label(stats_frame, text='Entry File: -', bg='#222222', fg='#aaaaaa', anchor='w')
        self.entry_file_label.grid(row=0, column=0, sticky='w')
        self.exit_file_label = tk.Label(stats_frame, text='Exit File: -', bg='#222222', fg='#aaaaaa', anchor='w')
        self.exit_file_label.grid(row=1, column=0, sticky='w')
        self.entry_candle_label = tk.Label(stats_frame, text='Entry Candle: -', bg='#222222', fg='#aaaaaa', anchor='w', font=('Consolas', 9))
        self.entry_candle_label.grid(row=2, column=0, sticky='w', pady=(2,0))
        self.exit_candle_label = tk.Label(stats_frame, text='Exit Candle: -', bg='#222222', fg='#aaaaaa', anchor='w', font=('Consolas', 9))
        self.exit_candle_label.grid(row=3, column=0, sticky='w')
        self.pnl_label = tk.Label(stats_frame, text='Result: -', bg='#222222', fg='#aaaaaa', anchor='w')
        self.pnl_label.grid(row=4, column=0, sticky='w', pady=(4,0))

        # Navigation buttons
        nav_frame = tk.Frame(root, bg='#222222')
        nav_frame.pack(pady=(0,10))
        # Navigation buttons now green for clearer visibility
        self.btn_back = tk.Button(
            nav_frame,
            text='Back',
            width=14,
            command=self.prev_trade,
            bg='#2e7d32', fg='white', activebackground='#388e3c', activeforeground='white'
        )
        self.btn_back.grid(row=0, column=0, padx=12)
        self.btn_next = tk.Button(
            nav_frame,
            text='Next',
            width=14,
            command=self.next_trade,
            bg='#2e7d32', fg='white', activebackground='#388e3c', activeforeground='white'
        )
        self.btn_next.grid(row=0, column=1, padx=12)

        # Key bindings
        root.bind('<Left>', lambda e: self.prev_trade())
        root.bind('<Right>', lambda e: self.next_trade())
        root.bind('<Escape>', lambda e: root.quit())

        self.refresh_display()

    # ---------------------------------------------------------------
    def has_trades(self):
        return len(self.trades) > 0

    def current_trade(self) -> Optional[Dict[str, Any]]:
        if not self.has_trades():
            return None
        if 0 <= self.index < len(self.trades):
            return self.trades[self.index]
        return None

    def load_image(self, path: Path, max_size=(560, 520)):
        try:
            with Image.open(path) as im:
                im.thumbnail(max_size)
                return ImageTk.PhotoImage(im)
        except Exception:
            return None

    def format_candle(self, idx: Optional[int]):
        if idx is None:
            return '-'
        data = extract_candle(self.df, idx)
        if not data:
            return '-'
        ts, o, h, low_v, c, v = data
        return f"{ts}  O:{o} H:{h} L:{low_v} C:{c} V:{v}"

    def compute_pnl(self, trade: Dict[str, Any]) -> float:
        e_idx = filename_to_index(trade['entry_file'].name, len(self.df))
        x_idx = filename_to_index(trade['exit_file'].name, len(self.df))
        if e_idx is None or x_idx is None:
            return 0.0
        entry = close_price(self.df, e_idx)
        exit_p = close_price(self.df, x_idx)
        if trade['side'] == 'BUY':
            return exit_p - entry
        else:
            return entry - exit_p

    def refresh_display(self):
        trade = self.current_trade()
        if not trade:
            self.left_label.config(text='No closed trades found.', image='')
            self.right_label.config(text='', image='')
            self.status.config(text='')
            self.entry_file_label.config(text='Entry File: -')
            self.exit_file_label.config(text='Exit File: -')
            self.entry_candle_label.config(text='Entry Candle: -')
            self.exit_candle_label.config(text='Exit Candle: -')
            self.pnl_label.config(text='Result: -')
            self.btn_back.config(state=tk.DISABLED)
            self.btn_next.config(state=tk.DISABLED)
            return

        # Images
        self.left_photo = self.load_image(trade['entry_file'])
        self.right_photo = self.load_image(trade['exit_file'])
        if self.left_photo:
            self.left_label.config(image=self.left_photo, text='')
        else:
            self.left_label.config(text=f"Missing {trade['entry_file'].name}")
        if self.right_photo:
            self.right_label.config(image=self.right_photo, text='')
        else:
            self.right_label.config(text=f"Missing {trade['exit_file'].name}")

        # Status
        self.status.config(text=f"Trade {self.index+1}/{len(self.trades)}  {trade['side']}  {trade['entry_file'].name} -> {trade['exit_file'].name}")

        # Candle details
        e_idx = filename_to_index(trade['entry_file'].name, len(self.df))
        x_idx = filename_to_index(trade['exit_file'].name, len(self.df))
        self.entry_file_label.config(text=f"Entry File: {trade['entry_file'].name}")
        self.exit_file_label.config(text=f"Exit File:  {trade['exit_file'].name}")
        self.entry_candle_label.config(text=f"Entry Candle: {self.format_candle(e_idx)}")
        self.exit_candle_label.config(text=f"Exit Candle:  {self.format_candle(x_idx)}")
        pnl = self.compute_pnl(trade)
        self.pnl_label.config(text=f"Result: {pnl:.2f}")

        # Nav button states
        if self.index <= 0:
            self.btn_back.config(state=tk.DISABLED)
        else:
            self.btn_back.config(state=tk.NORMAL)
        if self.index >= len(self.trades) - 1:
            self.btn_next.config(state=tk.DISABLED)
        else:
            self.btn_next.config(state=tk.NORMAL)

    def next_trade(self):
        if self.index < len(self.trades) - 1:
            self.index += 1
            self.refresh_display()

    def prev_trade(self):
        if self.index > 0:
            self.index -= 1
            self.refresh_display()


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='View paired entry/exit trade screenshots side-by-side.')
    parser.add_argument('--ticker', required=True, help='Ticker symbol, e.g. BTCUSDT')
    parser.add_argument('--interval', required=True, help='Chart interval, e.g. 15m')
    parser.add_argument('--time', required=True, help='Time interval, e.g. "1 month"')
    parser.add_argument('--refresh', action='store_true', help='Re-fetch data CSV (propagated to ensure_data)')
    parser.add_argument('--source', choices=['binance','forex'], default='binance', help='Data source for underlying OHLC CSV.')
    args = parser.parse_args()

    # Ensure data to load dataframe for candle details
    csv_path = ensure_data(args.ticker, args.interval, args.time, args.refresh, args.source)
    df = load_dataframe(csv_path)

    paths = build_processed_paths(args.ticker, args.interval, args.time)
    missing_dirs = [k for k,v in paths.items() if k not in ('base',) and not v.exists()]
    if missing_dirs:
        print('[WARN] Some processed subfolders are missing. Continuing with existing ones.')

    trades = reconstruct_trades(paths)

    root = tk.Tk()
    TradeViewerApp(root, trades, df)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
