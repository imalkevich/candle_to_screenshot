import argparse
from pathlib import Path
import shutil
import sys
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import re

# Reuse logic from existing modules by importing functions
from generate_screenshots import build_data_filename, ensure_data, load_dataframe, SCREENSHOTS_DIR

PROCESSED_DIR = Path('processed')


def build_screenshot_folder(ticker: str, interval: str, time_range: str) -> Path:
    sanitized_time = re.sub(r'\s+', '', time_range.lower())
    return SCREENSHOTS_DIR / f"{ticker.upper()}_{interval}_{sanitized_time}"


def build_processed_subfolders(ticker: str, interval: str, time_range: str):
    sanitized_time = re.sub(r'\s+', '', time_range.lower())
    base = PROCESSED_DIR / f"{ticker.upper()}_{interval}_{sanitized_time}"
    situation = base / 'situation'
    normal = base / 'normal'
    base.mkdir(parents=True, exist_ok=True)
    situation.mkdir(parents=True, exist_ok=True)
    normal.mkdir(parents=True, exist_ok=True)
    return base, situation, normal


def list_screenshots(folder: Path):
    return sorted([p for p in folder.glob('candle_*.png') if p.is_file()])


def determine_start_index(images, situation_dir: Path, normal_dir: Path):
    """Determine index to resume from by counting already labeled files.
    We assume labeled filenames keep original candle_XXXXX.png name when copied.
    """
    labeled = set()
    for d in (situation_dir, normal_dir):
        for p in d.glob('candle_*.png'):
            labeled.add(p.name)
    # find first image whose name not in labeled
    for idx, img in enumerate(images):
        if img.name not in labeled:
            return idx
    return len(images)  # all done


class LabelApp:
    def __init__(self, root, images, situation_dir: Path, normal_dir: Path):
        self.root = root
        self.images = images
        self.situation_dir = situation_dir
        self.normal_dir = normal_dir
        self.index = 0
        self.photo_cache = None
        # history stack of tuples (image_path, destination_dir) for undo
        self.history: list[tuple[Path, Path]] = []

        self.root.title('Candlestick Labeling')
        self.root.geometry('600x600')
        self.root.configure(bg='#222222')

        self.label_frame = tk.Frame(self.root, bg='#222222')
        self.label_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Label(self.label_frame, bg='#222222')
        self.canvas.pack(pady=10)

        btn_frame = tk.Frame(self.root, bg='#222222')
        btn_frame.pack(pady=10)

        self.btn_yes = tk.Button(btn_frame, text='Yes (Situation)', width=18, command=self.mark_yes, bg='#2e7d32', fg='white')
        self.btn_yes.grid(row=0, column=0, padx=10, pady=(0,4))

        self.btn_no = tk.Button(btn_frame, text='No (Normal)', width=18, command=self.mark_no, bg='#c62828', fg='white')
        self.btn_no.grid(row=0, column=1, padx=10, pady=(0,4))

        # Back button centered beneath Yes/No spanning both columns
        self.btn_back = tk.Button(btn_frame, text='Back', width=20, command=self.undo_last, bg='#000000', fg='white')
        self.btn_back.grid(row=1, column=0, columnspan=2, pady=(6,0))

        self.status = tk.Label(self.root, text='', bg='#222222', fg='#cccccc')
        self.status.pack(pady=5)

        self.root.bind('<Left>', lambda e: self.mark_no())
        self.root.bind('<Right>', lambda e: self.mark_yes())
        self.root.bind('<Escape>', lambda e: self.root.quit())
        self.root.bind('<BackSpace>', lambda e: self.undo_last())

        self.update_image()

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

    def mark_yes(self):
        self.copy_current(self.situation_dir)
        self.advance()

    def mark_no(self):
        self.copy_current(self.normal_dir)
        self.advance()

    def undo_last(self):
        if not self.history:
            self.status.config(text=f"No action to undo. {self.index+1}/{len(self.images)}")
            return
        last_img, last_dir = self.history.pop()
        # Remove copied file if it still exists
        target = last_dir / last_img.name
        try:
            if target.exists():
                target.unlink()
        except Exception as e:
            messagebox.showwarning('Undo Warning', f'Could not remove {target.name}: {e}')
        # Move index back one (cannot go below 0)
        self.index = max(0, self.index - 1)
        self.update_image()
        self.status.config(text=f"Undid labeling of {last_img.name}. Re-label this image.")


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

    base, situation_dir, normal_dir = build_processed_subfolders(args.ticker, args.interval, args.time)

    # If restart requested, clear existing labeled files only (not screenshots)
    if args.restart:
        removed = 0
        for d in (situation_dir, normal_dir):
            for f in d.glob('candle_*.png'):
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    print(f"[WARN] Could not remove {f}: {e}")
        if removed:
            print(f"[INFO] Restart requested: removed {removed} previously labeled images.")
        else:
            print("[INFO] Restart requested: no existing labeled images to remove.")

    # Determine resume position
    start_index = 0 if args.restart else determine_start_index(images, situation_dir, normal_dir)
    if start_index >= len(images):
        print('[INFO] All images already labeled.')
        return 0

    root = tk.Tk()
    app = LabelApp(root, images, situation_dir, normal_dir)
    app.set_index(start_index)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
