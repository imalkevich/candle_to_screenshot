import argparse
from pathlib import Path
import shutil
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageTk
import re

# Reuse logic from existing modules by importing functions
from generate_screenshots import ensure_data, load_dataframe, SCREENSHOTS_DIR

PROCESSED_DIR = Path('processed')


def build_screenshot_folder(ticker: str, interval: str, time_range: str) -> Path:
    sanitized_time = re.sub(r'\s+', '', time_range.lower())
    return SCREENSHOTS_DIR / f"{ticker.upper()}_{interval}_{sanitized_time}"


def build_processed_subfolders(ticker: str, interval: str, time_range: str):
    sanitized_time = re.sub(r'\s+', '', time_range.lower())
    base = PROCESSED_DIR / f"{ticker.upper()}_{interval}_{sanitized_time}"
    situation = base / 'situation'
    normal = base / 'normal'
    exit_dir = base / 'exit'
    base.mkdir(parents=True, exist_ok=True)
    situation.mkdir(parents=True, exist_ok=True)
    normal.mkdir(parents=True, exist_ok=True)
    exit_dir.mkdir(parents=True, exist_ok=True)
    return base, situation, normal, exit_dir


def list_screenshots(folder: Path):
    return sorted([p for p in folder.glob('candle_*.png') if p.is_file()])


def determine_start_index(images, situation_dir: Path, normal_dir: Path, exit_dir: Path):
    """Determine index to resume from by counting already labeled files across all processed folders.
    We assume copied filenames keep original candle_XXXXX.png name.
    """
    labeled = set()
    for d in (situation_dir, normal_dir, exit_dir):
        for p in d.glob('candle_*.png'):
            labeled.add(p.name)
    for idx, img in enumerate(images):
        if img.name not in labeled:
            return idx
    return len(images)


class LabelApp:
    def __init__(self, root, images, situation_dir: Path, normal_dir: Path, exit_dir: Path, open_position: bool, ohlc_df):
        self.root = root
        self.images = images
        self.situation_dir = situation_dir
        self.normal_dir = normal_dir
        self.exit_dir = exit_dir
        self.open_position = open_position
        self.ohlc_df = ohlc_df  # pandas DataFrame with OHLC data
        self.index = 0
        self.photo_cache = None
        self.history: list[tuple[Path, Path]] = []  # file actions
        self.state_history: list[str] = []  # 'OPEN' / 'CLOSE' sequence for quicker reasoning (optional)
        self.trades: list[dict] = []  # {item_id, entry_idx, entry_price, exit_idx, exit_price}
        self.open_trade_item_id: str | None = None

        # Window setup
        self.root.title('Candlestick Labeling')
        self.root.configure(bg='#222222')
        self.root.geometry('1220x620')

        main_frame = tk.Frame(self.root, bg='#222222')
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(main_frame, bg='#222222')
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,4), pady=8)

        right_frame = tk.Frame(main_frame, bg='#222222', bd=1, relief=tk.SUNKEN)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(4,10), pady=8)

        # Right panel layout: separate frames for Trades and Statistics
        trades_section = tk.Frame(right_frame, bg='#222222')
        trades_section.pack(fill=tk.BOTH, expand=True, padx=0, pady=(4,2))
        tk.Label(trades_section, text='Trades', bg='#222222', fg='#dddddd', font=('Arial', 10, 'bold')).pack(anchor='n', pady=(0,2))
        columns = ('entry_date', 'entry_price', 'exit_date', 'exit_price', 'result')
        # Reduce height so statistics fit without needing scroll
        self.trade_table = ttk.Treeview(trades_section, columns=columns, show='headings', height=18)
        headings = ['Entry Date', 'Entry Price', 'Exit Date', 'Exit Price', 'Result']
        widths = [140, 90, 140, 90, 80]
        for col, head, w in zip(columns, headings, widths):
            self.trade_table.heading(col, text=head)
            self.trade_table.column(col, width=w, anchor='center')
        vsb = ttk.Scrollbar(trades_section, orient='vertical', command=self.trade_table.yview)
        self.trade_table.configure(yscrollcommand=vsb.set)
        self.trade_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        # Statistics separate section
        stats_section = tk.Frame(right_frame, bg='#222222')
        stats_section.pack(fill=tk.X, padx=4, pady=(4,6))
        tk.Label(stats_section, text='Statistics', bg='#222222', fg='#dddddd', font=('Arial', 10, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        self.stat_trades = tk.Label(stats_section, text='Number of trades: 0', bg='#222222', fg='#aaaaaa', anchor='w')
        self.stat_trades.grid(row=1, column=0, columnspan=2, sticky='w')
        self.stat_net = tk.Label(stats_section, text='Profit/Loss: 0.00', bg='#222222', fg='#aaaaaa', anchor='w')
        self.stat_net.grid(row=2, column=0, columnspan=2, sticky='w')
        self.stat_ratio = tk.Label(stats_section, text='Profit/Loss ratio: 0 / 0', bg='#222222', fg='#aaaaaa', anchor='w')
        self.stat_ratio.grid(row=3, column=0, columnspan=2, sticky='w')
        self.stat_factor = tk.Label(stats_section, text='Profit factor: 0.00', bg='#222222', fg='#aaaaaa', anchor='w')
        self.stat_factor.grid(row=4, column=0, columnspan=2, sticky='w')

        # Chart display
        self.canvas = tk.Label(left_frame, bg='#222222')
        self.canvas.pack(pady=10)

        # Buttons
        btn_frame = tk.Frame(left_frame, bg='#222222')
        btn_frame.pack(pady=6)
        self.btn_yes = tk.Button(btn_frame, text='Yes (Situation)', width=18, command=self.primary_action, bg='#2e7d32', fg='white')
        self.btn_yes.grid(row=0, column=0, padx=10, pady=(0,4))
        self.btn_no = tk.Button(btn_frame, text='No (Normal)', width=18, command=self.secondary_action, bg='#c62828', fg='white')
        self.btn_no.grid(row=0, column=1, padx=10, pady=(0,4))
        self.btn_back = tk.Button(btn_frame, text='Back', width=20, command=self.undo_last, bg='#000000', fg='white')
        self.btn_back.grid(row=1, column=0, columnspan=2, pady=(6,0))

        self.status = tk.Label(left_frame, text='', bg='#222222', fg='#cccccc')
        self.status.pack(pady=4)

        # Candle info label (time, O,H,L,C,V)
        self.candle_info = tk.Label(left_frame, text='', bg='#222222', fg='#aaaaaa', font=('Consolas', 9))
        self.candle_info.pack(pady=(0,6))

        # Shortcuts
        self.root.bind('<Return>', lambda e: self.primary_action())
        self.root.bind('<space>', lambda e: self.secondary_action())
        self.root.bind('<BackSpace>', lambda e: self.undo_last())
        self.root.bind('<Escape>', lambda e: self.root.quit())

        # Initial rendering and preload of existing trades
        self.update_image()
        self.update_button_states()
        self.preload_trades()
        self.update_stats()

    # --- State & UI helpers ---
    def update_button_states(self):
        """Adjust button labels/colors based on whether a position is currently open."""
        if self.open_position:
            # Need an exit
            self.btn_yes.config(text='Exit', bg='#fdd835', fg='black')  # Yellow
            self.btn_no.config(text='Continue', bg='#c62828', fg='white')
        else:
            self.btn_yes.config(text='Yes (Situation)', bg='#2e7d32', fg='white')
            self.btn_no.config(text='No (Normal)', bg='#c62828', fg='white')

    # --- Actions ---
    def primary_action(self):
        if self.open_position:
            self.mark_exit()
        else:
            self.mark_situation()

    # --- Trade helpers ---
    def _filename_to_row_index(self, filename: str) -> int | None:
        """Extract 0-based row index from candle_00001 style filename.
        Returns None if pattern not matched or out of range.
        """
        m = re.search(r'(\d+)', filename)
        if not m:
            return None
        # Filenames are 1-based; convert to 0-based
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(self.ohlc_df):
            return idx
        return None

    # --- Unified candle data retrieval ---
    def _get_candle_data(self, idx: int):
        """Return tuple (timestamp, open, high, low, close, volume) for a dataframe row index.
        Handles multiple possible column naming conventions and timestamp fallbacks.
        Returns None if idx out of range or an unexpected error occurs.
        Timestamp preference order: open_time -> close_time -> index value -> ''
        Column name variants supported: Open/High/Low/Close/Volume OR lower-case equivalents.
        """
        try:
            if idx < 0 or idx >= len(self.ohlc_df):
                return None
            row = self.ohlc_df.iloc[idx]
            cols = self.ohlc_df.columns
            # Timestamp resolution
            if 'open_time' in cols:
                ts = row['open_time']
            elif 'close_time' in cols:
                ts = row['close_time']
            else:
                try:
                    ts = self.ohlc_df.index[idx]
                except Exception:
                    ts = ''
            # Column variants
            open_col = 'Open' if 'Open' in row else ('open' if 'open' in row else None)
            high_col = 'High' if 'High' in row else ('high' if 'high' in row else None)
            low_col = 'Low' if 'Low' in row else ('low' if 'low' in row else None)
            close_col = 'Close' if 'Close' in row else ('close' if 'close' in row else None)
            vol_col = 'Volume' if 'Volume' in row else ('volume' if 'volume' in row else None)
            if not all([open_col, high_col, low_col, close_col]):
                # Required OHLC columns missing – return None to signal failure
                return None
            o = row[open_col]
            h = row[high_col]
            low_v = row[low_col]
            c = row[close_col]
            v = row[vol_col] if vol_col else ''
            return ts, o, h, low_v, c, v
        except Exception:
            return None

    def _row_entry_values(self, idx: int):
        data = self._get_candle_data(idx)
        if not data:
            return '', 0.0
        ts, _o, _h, _l, c, _v = data
        try:
            price = float(c)
        except Exception:
            price = 0.0
        return ts, price

    def _add_trade_entry(self, filename: str):
        idx = self._filename_to_row_index(filename)
        if idx is None:
            return None
        dt, price = self._row_entry_values(idx)
        item_id = self.trade_table.insert('', tk.END, values=(dt, f"{price:.2f}", '', '', ''))
        self.trades.append({'item_id': item_id, 'entry_idx': idx, 'entry_price': price, 'exit_idx': None, 'exit_price': None})
        self.open_trade_item_id = item_id
        return item_id

    def _close_trade(self, filename: str):
        if not self.open_trade_item_id:
            return
        idx = self._filename_to_row_index(filename)
        if idx is None:
            return
        dt, price = self._row_entry_values(idx)
        # Find trade dict
        trade = next((t for t in reversed(self.trades) if t['item_id'] == self.open_trade_item_id), None)
        if not trade:
            return
        trade['exit_idx'] = idx
        trade['exit_price'] = price
        # Sell-only (short/mean-reversion) assumption: profit when price after entry is LOWER
        # So result = entry - exit
        result = trade['entry_price'] - price
        # Update tree item
        self.trade_table.item(self.open_trade_item_id, values=(
            self.trade_table.set(self.open_trade_item_id, 'entry_date'),
            self.trade_table.set(self.open_trade_item_id, 'entry_price'),
            dt, f"{price:.2f}", f"{result:.2f}"
        ))
        # Clear open pointer
        self.open_trade_item_id = None
        self.update_stats()

    def preload_trades(self):
        """Reconstruct trade table from existing situation/exit images.
        Pair situations with the next chronological exit after them (if any).
        """
        situation_files = sorted(self.situation_dir.glob('candle_*.png'), key=lambda p: p.name)
        exit_files = sorted(self.exit_dir.glob('candle_*.png'), key=lambda p: p.name)
        used_exits = set()
        # Build list of available exits with numeric index for efficient pairing
        def file_num(p: Path):
            m = re.search(r'(\d+)', p.name)
            return int(m.group(1)) if m else 10**12
        exit_with_nums = [(file_num(f), f) for f in exit_files]
        for s in situation_files:
            s_num = file_num(s)
            # find earliest exit with num > s_num not used
            candidate = None
            for num, f in exit_with_nums:
                if num > s_num and f not in used_exits:
                    candidate = f
                    used_exits.add(f)
                    break
            # Add entry row
            self._add_trade_entry(s.name)
            if candidate is not None:
                # Close it
                prev_open_id = self.open_trade_item_id
                self._close_trade(candidate.name)
                # Ensure open pointer stays None after closing
                if self.open_trade_item_id == prev_open_id:
                    self.open_trade_item_id = None
        # If resume had an open position, open_trade_item_id points to last row
        # No further action needed
        self.update_stats()

    def secondary_action(self):
        # Always normal/continue
        self.mark_normal()

    def mark_situation(self):
        current = self.current_image()
        fname = current.name if current else 'candle_?????.png'
        self.copy_current(self.situation_dir)
        self.open_position = True
        self.history.append(('STATE', 'OPEN'))
        # Add trade entry row
        self._add_trade_entry(fname)
        self.advance()
        self.update_button_states()

    def mark_normal(self):
        self.copy_current(self.normal_dir)
        self.advance()

    def mark_exit(self):
        current = self.current_image()
        fname = current.name if current else 'candle_?????.png'
        self.copy_current(self.exit_dir)
        self.open_position = False
        self.history.append(('STATE', 'CLOSE'))
        # Close trade row
        self._close_trade(fname)
        self.advance()
        self.update_button_states()

    def set_index(self, value):
        self.index = value
        self.update_image()

    def current_image(self):
        if 0 <= self.index < len(self.images):
            return self.images[self.index]
        return None

    def update_image(self):
        img_path = self.current_image()
        if img_path is None:
            self.canvas.config(image='', text='All images labeled. You can close now.')
            self.status.config(text=f"Done: {len(self.images)}/{len(self.images)}")
            self.btn_yes.config(state=tk.DISABLED)
            self.btn_no.config(state=tk.DISABLED)
            self.candle_info.config(text='')
            return
        try:
            with Image.open(img_path) as im:
                # Scale to fit window while preserving aspect
                max_w, max_h = 560, 480
                im.thumbnail((max_w, max_h))
                self.photo_cache = ImageTk.PhotoImage(im)
                self.canvas.config(image=self.photo_cache, text='')
        except Exception as e:
            self.canvas.config(text=f"Error loading image: {e}")
        self.status.config(text=f"Image {self.index+1}/{len(self.images)}: {img_path.name}")
        self.update_candle_info(img_path.name)

    def update_candle_info(self, filename: str):
        idx = self._filename_to_row_index(filename)
        if idx is None:
            self.candle_info.config(text='')
            return
        data = self._get_candle_data(idx)
        if not data:
            self.candle_info.config(text='')
            return
        ts, o, h, low_v, c, v = data
        self.candle_info.config(text=f"{ts}  O:{o} H:{h} L:{low_v} C:{c} V:{v}")

    def copy_current(self, destination_dir: Path):
        img_path = self.current_image()
        if img_path is None:
            return
        target = destination_dir / img_path.name
        try:
            if not target.exists():
                shutil.copy2(img_path, target)
                # push to history only when newly copied
                self.history.append((img_path, destination_dir))
        except Exception as e:
            messagebox.showerror('Copy Error', f'Failed to copy {img_path.name}: {e}')

    def advance(self):
        self.index += 1
        self.update_image()

    # Old mark_yes/mark_no kept for compatibility (not used directly)
    def mark_yes(self):
        self.primary_action()

    def mark_no(self):
        self.secondary_action()

    def undo_last(self):
        if not self.history:
            self.status.config(text=f"No action to undo. {self.index+1}/{len(self.images)}")
            return
        last_item = self.history.pop()
        if isinstance(last_item, tuple) and last_item and last_item[0] == 'STATE':
            marker_type = last_item[1]
            if marker_type == 'OPEN':
                # Undo an OPEN: remove last trade row
                if self.trades:
                    trade = self.trades.pop()
                    try:
                        self.trade_table.delete(trade['item_id'])
                    except Exception:
                        pass
                self.open_position = False
                self.open_trade_item_id = None
                self.update_stats()
            elif marker_type == 'CLOSE':
                # Undo a CLOSE: find most recent closed trade and clear exit fields
                for trade in reversed(self.trades):
                    if trade['exit_idx'] is not None:
                        trade['exit_idx'] = None
                        trade['exit_price'] = None
                        # Update row removing exit columns
                        self.trade_table.item(trade['item_id'], values=(
                            self.trade_table.set(trade['item_id'], 'entry_date'),
                            self.trade_table.set(trade['item_id'], 'entry_price'),
                            '', '', ''
                        ))
                        self.open_trade_item_id = trade['item_id']
                        break
                self.open_position = True
                self.update_stats()
            self.status.config(text=f"Reverted state change ({marker_type}).")
            self.update_button_states()
            return
        # Otherwise it's a file copy tuple (img_path, destination_dir)
        last_img, last_dir = last_item
        target = last_dir / last_img.name
        try:
            if target.exists():
                target.unlink()
        except Exception as e:
            messagebox.showwarning('Undo Warning', f'Could not remove {target.name}: {e}')
        # Move index back, update display
        self.index = max(0, self.index - 1)
        self.update_image()
        self.status.config(text=f"Undid labeling of {last_img.name}. Re-label this image.")
        self.update_button_states()
        self.update_stats()

    # --- Statistics ---
    def update_stats(self):
        """Compute and display trade statistics for CLOSED trades only."""
        closed = [t for t in self.trades if t['exit_idx'] is not None]
        num = len(closed)
        if num == 0:
            self.stat_trades.config(text='Number of trades: 0')
            self.stat_net.config(text='Profit/Loss: 0.00')
            self.stat_ratio.config(text='Profit/Loss ratio: 0 / 0')
            self.stat_factor.config(text='Profit factor: 0.00')
            return
        results = []
        for t in closed:
            # Retrieve result from tree to ensure consistent formatting
            val = self.trade_table.set(t['item_id'], 'result')
            try:
                results.append(float(val))
            except (TypeError, ValueError):
                pass
        num = len(results)
        wins = [r for r in results if r > 0]
        losses = [r for r in results if r < 0]
        win_count = len(wins)
        loss_count = len(losses)
        net = sum(results)
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = -sum(losses) if losses else 0.0  # make positive
        # Profit/loss ratio: wins count / losses count (avoid div0)
        if loss_count == 0:
            ratio_text = f"{win_count} / {loss_count} (∞)" if win_count > 0 else "0 / 0"
        else:
            ratio_text = f"{win_count} / {loss_count} ({win_count/loss_count:.2f})"
        # Profit factor = gross_profit / gross_loss
        if gross_loss == 0:
            pf = float('inf') if gross_profit > 0 else 0.0
        else:
            pf = gross_profit / gross_loss
        self.stat_trades.config(text=f"Number of trades: {num}")
        self.stat_net.config(text=f"Profit/Loss: {net:.2f}")
        self.stat_ratio.config(text=f"Profit/Loss ratio: {ratio_text}")
        self.stat_factor.config(text=f"Profit factor: {pf:.2f}" if pf != float('inf') else "Profit factor: ∞")


def main():
    parser = argparse.ArgumentParser(description='Label candlestick screenshots with Yes/No into processed folders.')
    parser.add_argument('--ticker', required=True, help='Ticker symbol, e.g. BTCUSDT')
    parser.add_argument('--interval', required=True, help='Chart interval, e.g. 15m')
    parser.add_argument('--time', required=True, help='Time interval, e.g. "1 month"')
    parser.add_argument('--refresh', action='store_true', help='Re-fetch data even if CSV already exists (propagated)')
    parser.add_argument('--skip', type=int, default=480, help='Skip first N candles when generating screenshots if generation needed')
    parser.add_argument('--max-candles', type=int, default=96, dest='max_candles', help='Max candles per screenshot window if generation needed (default 96)')
    parser.add_argument('--restart', action='store_true', help='Start labeling from the first screenshot (clears existing labeled copies in processed folder)')
    args = parser.parse_args()

    # Ensure OHLC data file exists (reuse generation logic's ensure_data)
    csv_path = ensure_data(args.ticker, args.interval, args.time, args.refresh)

    # Ensure screenshots exist; if not, generate them by invoking the same functions
    screenshot_folder = build_screenshot_folder(args.ticker, args.interval, args.time)
    if not screenshot_folder.exists() or not any(screenshot_folder.glob('candle_*.png')):
        print('[INFO] No screenshots found. Generating...')
        df = load_dataframe(csv_path)
        from generate_screenshots import generate_screenshots
        generate_screenshots(df, args.ticker, args.interval, args.time, start_skip=args.skip, max_candles=args.max_candles)
    else:
        print(f'[INFO] Using existing screenshots: {screenshot_folder}')

    images = list_screenshots(screenshot_folder)
    if not images:
        print('[WARN] No images to label after generation attempt. Exiting.')
        return 0

    base, situation_dir, normal_dir, exit_dir = build_processed_subfolders(args.ticker, args.interval, args.time)

    # If restart requested, clear existing labeled files only (not screenshots)
    if args.restart:
        removed = 0
        for d in (situation_dir, normal_dir, exit_dir):
            for f in d.glob('candle_*.png'):
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    print(f"[WARN] Could not remove {f}: {e}")
        if removed:
            print(f"[INFO] Restart requested: removed {removed} previously labeled images (including exit events).")
        else:
            print("[INFO] Restart requested: no existing labeled images to remove.")

    # Determine resume position
    start_index = 0 if args.restart else determine_start_index(images, situation_dir, normal_dir, exit_dir)
    if start_index >= len(images):
        print('[INFO] All images already labeled.')
        return 0

    # Detect open position state for resume logic:
    # Open if more situations than exits (an unclosed situation) or counts differ and situation > exit
    situation_count = len(list(situation_dir.glob('candle_*.png')))
    exit_count = len(list(exit_dir.glob('candle_*.png')))
    open_position = situation_count > exit_count

    # Load OHLC dataframe for trade table (ensure it's loaded even if screenshots pre-exist)
    ohlc_df = load_dataframe(csv_path)
    root = tk.Tk()
    app = LabelApp(root, images, situation_dir, normal_dir, exit_dir, open_position, ohlc_df)
    app.set_index(start_index)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
