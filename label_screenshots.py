import argparse
from typing import Optional, List, Dict, Any
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
    """Create processed subfolder structure supporting buy/sell operations.
    Folders:
      normal     - neutral/next images
      buy        - entry screenshots for long/buy positions
      buy_exit   - exit screenshots for buy positions
      sell       - entry screenshots for short/sell positions
      sell_exit  - exit screenshots for sell positions
    """
    sanitized_time = re.sub(r'\s+', '', time_range.lower())
    base = PROCESSED_DIR / f"{ticker.upper()}_{interval}_{sanitized_time}"
    normal = base / 'normal'
    buy = base / 'buy'
    buy_exit = base / 'buy_exit'
    sell = base / 'sell'
    sell_exit = base / 'sell_exit'
    base.mkdir(parents=True, exist_ok=True)
    for d in (normal, buy, buy_exit, sell, sell_exit):
        d.mkdir(parents=True, exist_ok=True)
    return base, normal, buy, buy_exit, sell, sell_exit


def list_screenshots(folder: Path):
    return sorted([p for p in folder.glob('candle_*.png') if p.is_file()])


def determine_start_index(images, *dirs: Path):
    labeled = set()
    for d in dirs:
        for p in d.glob('candle_*.png'):
            labeled.add(p.name)
    for idx, img in enumerate(images):
        if img.name not in labeled:
            return idx
    return len(images)


class LabelApp:
    def __init__(self, root, images,
                 normal_dir: Path,
                 buy_dir: Path, buy_exit_dir: Path,
                 sell_dir: Path, sell_exit_dir: Path,
                 open_side,
                 ohlc_df):
        # Core state
        self.root = root
        self.images = images
        self.normal_dir = normal_dir
        self.buy_dir = buy_dir
        self.buy_exit_dir = buy_exit_dir
        self.sell_dir = sell_dir
        self.sell_exit_dir = sell_exit_dir
        self.open_side = open_side
        self.ohlc_df = ohlc_df  # pandas DataFrame
        self.index = 0
        self.photo_cache = None
        self.history: List[Any] = []  # file copy actions and state markers
        self.state_history: List[str] = []
        self.trades: List[Dict[str, Any]] = []
        self.open_trade_item_id: Optional[str] = None

        # Window setup
        self.root.title('Candlestick Labeling')
        self.root.configure(bg='#222222')
        # Increased width to accommodate added 'Side' column and reduce layout jumping
        self.root.geometry('1320x640')
        try:
            self.root.minsize(1200, 620)
        except Exception:
            pass

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
        columns = ('side', 'entry_date', 'entry_price', 'exit_date', 'exit_price', 'result')
        # Reduce height so statistics fit without needing scroll
        self.trade_table = ttk.Treeview(trades_section, columns=columns, show='headings', height=18)
        headings = ['Side', 'Entry Date', 'Entry Price', 'Exit Date', 'Exit Price', 'Result']
        widths = [60, 140, 90, 140, 90, 80]
        for col, head, w in zip(columns, headings, widths):
            self.trade_table.heading(col, text=head)
            # Disable stretching so columns keep fixed width and window doesn't jump
            self.trade_table.column(col, width=w, anchor='center', stretch=False)
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
        self.btn_buy = tk.Button(btn_frame, text='Buy', width=12, command=lambda: self.open_trade('BUY'), bg='#2e7d32', fg='white')
        self.btn_buy.grid(row=0, column=0, padx=6, pady=(0,4))
        self.btn_sell = tk.Button(btn_frame, text='Sell', width=12, command=lambda: self.open_trade('SELL'), bg='#c62828', fg='white')
        self.btn_sell.grid(row=0, column=1, padx=6, pady=(0,4))
        self.btn_next = tk.Button(btn_frame, text='Next', width=12, command=self.mark_normal, bg='#555555', fg='white')
        self.btn_next.grid(row=0, column=2, padx=6, pady=(0,4))
        self.btn_back = tk.Button(btn_frame, text='Back', width=20, command=self.undo_last, bg='#000000', fg='white')
        self.btn_back.grid(row=1, column=0, columnspan=3, pady=(6,0))

        self.status = tk.Label(left_frame, text='', bg='#222222', fg='#cccccc')
        self.status.pack(pady=4)

        # Candle info label (time, O,H,L,C,V)
        self.candle_info = tk.Label(left_frame, text='', bg='#222222', fg='#aaaaaa', font=('Consolas', 9))
        self.candle_info.pack(pady=(0,6))

        # Shortcuts
        self.root.bind('<Up>', lambda e: self.open_trade('BUY'))
        self.root.bind('<Down>', lambda e: self.open_trade('SELL'))
        self.root.bind('<space>', lambda e: self.mark_normal())
        self.root.bind('<BackSpace>', lambda e: self.undo_last())
        self.root.bind('<Escape>', lambda e: self.root.quit())

        # Initial rendering and preload of existing trades
        self.update_image()
        self.update_button_states()
        self.preload_trades()
        self.update_stats()

    # --- Button / state helpers ---
    def update_button_states(self):
        """Configure button states based on whether a side is currently open."""
        if self.open_side is None:
            # No open trade: Buy/Sell enabled, standard colors, Next enabled
            self.btn_buy.config(text='Buy', state=tk.NORMAL, command=lambda: self.open_trade('BUY'), bg='#2e7d32', fg='white')
            self.btn_sell.config(text='Sell', state=tk.NORMAL, command=lambda: self.open_trade('SELL'), bg='#c62828', fg='white')
            self.btn_next.config(text='Next', state=tk.NORMAL, command=self.mark_normal, bg='#555555', fg='white')
        else:
            # One side open - allow exit via that side's button; disable other side
            if self.open_side == 'BUY':
                self.btn_buy.config(text='Exit (Buy)', state=tk.NORMAL, command=self.mark_exit, bg='#fdd835', fg='black')
                self.btn_sell.config(state=tk.DISABLED)
            else:
                self.btn_sell.config(text='Exit (Sell)', state=tk.NORMAL, command=self.mark_exit, bg='#fdd835', fg='black')
                self.btn_buy.config(state=tk.DISABLED)
            # Next still available to continue labeling intermediate candles
            self.btn_next.config(text='Next', state=tk.NORMAL, command=self.mark_normal, bg='#555555', fg='white')

    # --- Trade lifecycle actions ---
    def open_trade(self, side: str):
        if self.open_side is not None:
            # Already have open trade; ignore
            return
        current = self.current_image()
        if not current:
            return
        fname = current.name
        # Copy to appropriate side entry folder
        target_dir = self.buy_dir if side == 'BUY' else self.sell_dir
        self.copy_current(target_dir)
        # Record state change after file copy
        self.history.append(('STATE', f'OPEN_{side}'))
        # Add trade entry row (internal only; store side)
        self._add_trade_entry(fname, side)
        self.open_side = side
        self.advance()
        self.update_button_states()

    def mark_exit(self):
        if self.open_side is None:
            return
        side = self.open_side
        current = self.current_image()
        fname = current.name if current else 'candle_?????.png'
        # Copy to appropriate exit folder
        target_dir = self.buy_exit_dir if side == 'BUY' else self.sell_exit_dir
        self.copy_current(target_dir)
        # Record state change
        self.history.append(('STATE', f'CLOSE_{side}'))
        # Close trade row
        self._close_trade(fname)
        self.open_side = None
        self.advance()
        self.update_button_states()

    def mark_normal(self):
        # Always just copy to normal and advance (independent of open trade)
        self.copy_current(self.normal_dir)
        self.advance()

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

    def _add_trade_entry(self, filename: str, side: str):
        idx = self._filename_to_row_index(filename)
        if idx is None:
            return None
        dt, price = self._row_entry_values(idx)
        item_id = self.trade_table.insert('', tk.END, values=(side, dt, f"{price:.4f}", '', '', ''))
        self.trades.append({'item_id': item_id, 'entry_idx': idx, 'entry_price': price,
                            'exit_idx': None, 'exit_price': None, 'side': side})
        self.open_trade_item_id = item_id
        return item_id

    def _close_trade(self, filename: str):
        if not self.open_trade_item_id:
            return
        idx = self._filename_to_row_index(filename)
        if idx is None:
            return
        dt, price = self._row_entry_values(idx)
        trade = next((t for t in reversed(self.trades) if t['item_id'] == self.open_trade_item_id), None)
        if not trade:
            return
        trade['exit_idx'] = idx
        trade['exit_price'] = price
        # PnL logic depends on side: BUY -> exit - entry; SELL -> entry - exit
        if trade['side'] == 'BUY':
            result = price - trade['entry_price']
        else:
            result = trade['entry_price'] - price
        self.trade_table.item(self.open_trade_item_id, values=(
            trade['side'],
            self.trade_table.set(self.open_trade_item_id, 'entry_date'),
            self.trade_table.set(self.open_trade_item_id, 'entry_price'),
            dt, f"{price:.4f}", f"{result:.4f}"
        ))
        self.open_trade_item_id = None
        self.update_stats()

    def preload_trades(self):
        """Reconstruct existing trades from buy/sell + exit folders.
        We pair each entry with the next exit in its corresponding side's exit folder.
        If there are more entries than exits, the last unmatched entry is considered open.
        """
        def file_num(p: Path):
            m = re.search(r'(\d+)', p.name)
            return int(m.group(1)) if m else 10**12
        # Prepare lists
        buy_entries = sorted(self.buy_dir.glob('candle_*.png'), key=lambda p: p.name)
        buy_exits = sorted(self.buy_exit_dir.glob('candle_*.png'), key=lambda p: p.name)
        sell_entries = sorted(self.sell_dir.glob('candle_*.png'), key=lambda p: p.name)
        sell_exits = sorted(self.sell_exit_dir.glob('candle_*.png'), key=lambda p: p.name)

        def pair_entries(entries, exits, side):
            used = set()
            exit_nums = [(file_num(f), f) for f in exits]
            last_open_trade_id = None
            for e in entries:
                e_num = file_num(e)
                # add trade entry row
                self._add_trade_entry(e.name, side)
                # attempt to find exit with num > e_num not used
                candidate = None
                for num, f in exit_nums:
                    if num > e_num and f not in used:
                        candidate = f
                        used.add(f)
                        break
                if candidate is not None:
                    prev_open = self.open_trade_item_id
                    self._close_trade(candidate.name)
                    if self.open_trade_item_id == prev_open:
                        self.open_trade_item_id = None
                else:
                    # remains open for now
                    last_open_trade_id = self.open_trade_item_id
            return last_open_trade_id

        last_buy_open = pair_entries(buy_entries, buy_exits, 'BUY')
        last_sell_open = pair_entries(sell_entries, sell_exits, 'SELL')

        # Determine which side is actually open (should not be both – if both, prefer most recent)
        self.open_trade_item_id = None
        self.open_side = None
        def trade_start_idx(item_id):
            if not item_id:
                return -1
            trade = next((t for t in self.trades if t['item_id'] == item_id), None)
            return trade['entry_idx'] if trade else -1
        b_idx = trade_start_idx(last_buy_open)
        s_idx = trade_start_idx(last_sell_open)
        if b_idx >= 0 and s_idx >= 0:
            if b_idx > s_idx:
                self.open_trade_item_id = last_buy_open
                self.open_side = 'BUY'
            else:
                self.open_trade_item_id = last_sell_open
                self.open_side = 'SELL'
        elif b_idx >= 0:
            self.open_trade_item_id = last_buy_open
            self.open_side = 'BUY'
        elif s_idx >= 0:
            self.open_trade_item_id = last_sell_open
            self.open_side = 'SELL'
        # stats update
        self.update_stats()
        # Rebuild synthetic history so undo works uniformly (root-cause approach vs fallback heuristics)
        self.rebuild_history()

    def rebuild_history(self):
        """Rebuild the history stack from existing labeled files in chronological order.
        This enables consistent single-step undo behavior after a resume.
        History model: sequence of (file_copy) followed immediately (for entries/exits) by a STATE marker.
        We infer chronology from filename numeric order.
        Limitations: Cannot distinguish interleaving of normals vs trades beyond filename order, which is acceptable
        because labeling progresses strictly forward.
        """
        self.history.clear()
        # Collect all labeled files with their semantic types
        def collect(dir_path: Path, kind: str):
            out = []
            for p in dir_path.glob('candle_*.png'):
                m = re.search(r'(\d+)', p.name)
                if not m:
                    continue
                out.append((int(m.group(1)), p, kind))
            return out
        items = []
        items += collect(self.normal_dir, 'NORMAL')
        items += collect(self.buy_dir, 'BUY_ENTRY')
        items += collect(self.buy_exit_dir, 'BUY_EXIT')
        items += collect(self.sell_dir, 'SELL_ENTRY')
        items += collect(self.sell_exit_dir, 'SELL_EXIT')
        # Sort by candle number to recreate chronological order
        items.sort(key=lambda x: x[0])
        # We'll simulate history: for each entry/exit, push file tuple then STATE marker; for normal just file tuple.
        # For file copy we need the original screenshot path (self.images[index-1]) but we only have filename.
        # We'll reconstruct by mapping filename -> source path via self.images.
        filename_to_source = {p.name: p for p in self.images}
        for _num, file_path, kind in items:
            src = filename_to_source.get(file_path.name)
            if not src:
                continue
            # Push synthetic file copy action
            self.history.append((src, file_path.parent))
            if kind == 'BUY_ENTRY':
                self.history.append(('STATE', 'OPEN_BUY'))
            elif kind == 'SELL_ENTRY':
                self.history.append(('STATE', 'OPEN_SELL'))
            elif kind == 'BUY_EXIT':
                self.history.append(('STATE', 'CLOSE_BUY'))
            elif kind == 'SELL_EXIT':
                self.history.append(('STATE', 'CLOSE_SELL'))

    # mark_normal already defined earlier (side-aware version)

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
            # All done: clear image and status
            self.canvas.config(image='', text='All images labeled. You can close now.')
            self.status.config(text='')
            self.btn_buy.config(state=tk.DISABLED)
            self.btn_sell.config(state=tk.DISABLED)
            self.btn_next.config(state=tk.DISABLED)
            self.candle_info.config(text='')
            return
        # Load & display image
        try:
            with Image.open(img_path) as im:
                max_w, max_h = 560, 480
                im.thumbnail((max_w, max_h))
                self.photo_cache = ImageTk.PhotoImage(im)
                self.canvas.config(image=self.photo_cache, text='')
        except Exception as e:
            self.canvas.config(text=f"Error loading image: {e}")
        # Status: filename + position (e.g., candle_00042.png 42/2400)
        self.status.config(text=f"{img_path.name} {self.index+1}/{len(self.images)}")
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

    def undo_last(self):
        if not self.history:
            # Allow pure navigation backwards even if no undoable action exists
            if self.index > 0:
                # With reconstructed history, this branch should rarely execute (only at first image)
                self.index -= 1
                self.update_image()
            else:
                # At first image: show its filename (if any)
                self.update_image()
            return
        last_item = self.history.pop()
        if isinstance(last_item, tuple) and last_item and last_item[0] == 'STATE':
            marker_type = last_item[1]
            if marker_type.startswith('OPEN_'):
                # Undo an OPEN_{SIDE}
                if self.trades:
                    trade = self.trades.pop()
                    try:
                        self.trade_table.delete(trade['item_id'])
                    except Exception:
                        pass
                self.open_side = None
                self.open_trade_item_id = None
                self.update_stats()
            elif marker_type.startswith('CLOSE_'):
                # Undo a CLOSE_{SIDE}
                for trade in reversed(self.trades):
                    if trade['exit_idx'] is not None:
                        trade['exit_idx'] = None
                        trade['exit_price'] = None
                        self.trade_table.item(trade['item_id'], values=(
                            trade.get('side',''),
                            self.trade_table.set(trade['item_id'], 'entry_date'),
                            self.trade_table.set(trade['item_id'], 'entry_price'),
                            '', '', ''
                        ))
                        self.open_trade_item_id = trade['item_id']
                        self.open_side = trade.get('side')
                        break
                self.update_stats()
            # Also remove the immediately preceding file copy entry if present so one Back press is atomic
            if self.history and isinstance(self.history[-1], tuple) and isinstance(self.history[-1][0], Path):
                file_item = self.history.pop()
                img_path_obj, dest_dir = file_item
                target_file = dest_dir / img_path_obj.name
                try:
                    if target_file.exists():
                        target_file.unlink()
                except Exception:
                    pass
                # Move index back to reflect removal
                self.index = max(0, self.index - 1)
                self.update_image()
            # Keep only filename in status
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
        # Only filename shown (update_image already sets it)
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
        self.stat_net.config(text=f"Profit/Loss: {net:.4f}")
        self.stat_ratio.config(text=f"Profit/Loss ratio: {ratio_text}")
        self.stat_factor.config(text=f"Profit factor: {pf:.4f}" if pf != float('inf') else "Profit factor: ∞")


def main():
    parser = argparse.ArgumentParser(description='Label candlestick screenshots with Buy/Sell labeling into processed folders.')
    parser.add_argument('--ticker', required=True, help='Ticker symbol, e.g. BTCUSDT')
    parser.add_argument('--interval', required=True, help='Chart interval, e.g. 15m')
    parser.add_argument('--time', required=True, help='Time interval, e.g. "1 month"')
    parser.add_argument('--refresh', action='store_true', help='Re-fetch data even if CSV already exists (propagated)')
    parser.add_argument('--source', choices=['binance','forex'], default='binance', help='Data source (binance or forex) used for underlying CSV selection.')
    parser.add_argument('--skip', type=int, default=480, help='Skip first N candles when generating screenshots if generation needed')
    parser.add_argument('--max-candles', type=int, default=96, dest='max_candles', help='Max candles per screenshot window if generation needed (default 96)')
    parser.add_argument('--restart', action='store_true', help='Start labeling from the first screenshot (clears existing labeled copies in processed folder)')
    args = parser.parse_args()

    # Ensure OHLC data file exists (reuse generation logic's ensure_data) with source
    csv_path = ensure_data(args.ticker, args.interval, args.time, args.refresh, args.source)

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

    base, normal_dir, buy_dir, buy_exit_dir, sell_dir, sell_exit_dir = build_processed_subfolders(args.ticker, args.interval, args.time)

    # If restart requested, clear existing labeled files only (not screenshots)
    if args.restart:
        removed = 0
        for d in (normal_dir, buy_dir, buy_exit_dir, sell_dir, sell_exit_dir):
            for f in d.glob('candle_*.png'):
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    print(f"[WARN] Could not remove {f}: {e}")
        msg = f"removed {removed} previously labeled images" if removed else "no existing labeled images to remove"
        print(f"[INFO] Restart requested: {msg}.")

    # Determine resume position
    start_index = 0 if args.restart else determine_start_index(images, normal_dir, buy_dir, buy_exit_dir, sell_dir, sell_exit_dir)
    if start_index >= len(images):
        print('[INFO] All images already labeled.')
        return 0

    # Detect open side for resume (if any) based on unmatched entry vs exit counts per side
    buy_entries = len(list(buy_dir.glob('candle_*.png')))
    buy_exits = len(list(buy_exit_dir.glob('candle_*.png')))
    sell_entries = len(list(sell_dir.glob('candle_*.png')))
    sell_exits = len(list(sell_exit_dir.glob('candle_*.png')))
    open_side = None
    if buy_entries > buy_exits:
        open_side = 'BUY'
    if sell_entries > sell_exits:
        # If both appear open (shouldn't), choose the most recent by filename index
        if open_side == 'BUY':
            # compare latest unmatched entry indices
            def last_idx(dir_path):
                files = sorted(dir_path.glob('candle_*.png'))
                if not files:
                    return -1
                m = re.search(r'(\d+)', files[-1].name)
                return int(m.group(1)) if m else -1
            if last_idx(sell_dir) > last_idx(buy_dir):
                open_side = 'SELL'
        else:
            open_side = 'SELL'

    # Load OHLC dataframe for trade table (ensure it's loaded even if screenshots pre-exist)
    ohlc_df = load_dataframe(csv_path)
    root = tk.Tk()
    app = LabelApp(root, images, normal_dir, buy_dir, buy_exit_dir, sell_dir, sell_exit_dir, open_side, ohlc_df)
    app.set_index(start_index)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
