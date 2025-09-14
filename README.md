# Candle to Screenshot Utilities

This repository currently provides a Python script to download historical OHLC (candlestick) data from the Binance public API.

## Files

* `download_ohlc.py` – Script that pulls OHLC data for a symbol / interval / time range and saves to a CSV inside `data/` automatically.
* `generate_screenshots.py` – Generates sequential candlestick PNG images from previously downloaded (or freshly refreshed) data.
* `.vscode/launch.json` – Debug configurations for running the script inside VS Code.
* `.vscode/tasks.json` – Task to install Python dependencies.
* `requirements.txt` – Python dependencies (`requests`, `pandas`).

## Prerequisites

* Python 3.9+ recommended
* VS Code with the official Python extension installed (`ms-python.python`). Without the extension the debug configuration type `python` will not be recognized.

## Install Dependencies

Run in an integrated terminal:

```powershell
python -m pip install -r requirements.txt
```

Or use the VS Code Task: Terminal > Run Task > "Install Python dependencies".

## Usage

Run the script specifying ticker, interval, and time range. The output filename is generated automatically:

```powershell
python download_ohlc.py --ticker BTCUSDT --interval 15m --time "1 month"
```

This creates (example) a file like:

```
data/BTCUSDT_15m_1month.csv
```

Pattern: `data/<TICKER>_<INTERVAL>_<TIMERANGE>.csv`

The `<TIMERANGE>` part removes spaces and lowercases (e.g. `1 month` -> `1month`, `3 Days` -> `3days`). If you rerun with the same parameters the file will be overwritten.

## Screenshot Generation

Create a set of incremental candlestick images (skipping the first 480 candles by default and limiting each frame to the last 96 candles by default – 96 = one day of 15m candles). For machine learning suitability, all date (x-axis) and price (y-axis) scales, ticks, and labels are removed so the model focuses only on raw candle shapes and relative structure:

```powershell
python generate_screenshots.py --ticker BTCUSDT --interval 15m --time "1 month"
```

Options:

* `--refresh` – Force re-fetch of OHLC data even if the CSV already exists.
* `--skip <N>` – Number of initial candles to ignore when starting screenshot generation (default 480). Screens will begin from candle `N+1`.
* `--max-candles <N>` – Maximum number of most recent candles rendered per screenshot window (default 96). Earlier candles are truncated visually once the window exceeds this count.

Output folder structure:

```
screenshots/
	BTCUSDT_15m_1month/
		candle_00481.png
		candle_00482.png
		...
```

Idempotency: Existing PNG files are skipped; re-running after interruption will only generate missing images.

Automatic cleanup: The target screenshot folder for the specified (ticker, interval, time range) is fully deleted before a new generation run to prevent stale or inconsistent frames from previous executions. Remove or comment this behavior in `generate_screenshots.py` if you prefer incremental appends.

If total candles <= skip value, no screenshots are produced.

## Manual Labeling UI

Use the labeling tool to classify each screenshot as a "situation" (Yes) or "normal" (No). The tool:

* Reuses existing data & screenshots; generates them if missing.
* Resumes where you left off by checking what has already been copied.
* Stores labeled copies under a mirrored folder name inside `processed/` with two subfolders: `situation/` and `normal/`.
* Supports keyboard shortcuts: Enter = Yes, Space = No, Backspace = Back (Undo), Escape = Quit.
* Back button (or Backspace) removes the last copied label file (if present) and shows the previous image for relabeling.

Run:

```powershell
python label_screenshots.py --ticker BTCUSDT --interval 15m --time "1 month"
```

Folder layout produced:

```
processed/
	BTCUSDT_15m_1month/
		situation/
			candle_00481.png
			...
		normal/
			candle_00482.png
			...
```

If screenshots are not present, they are generated first using the same defaults (`--skip 480`, `--max-candles 96`). Use `--refresh` to force a fresh CSV download prior to generation if needed.

You can safely close the UI mid-session; on restart it will continue from the first unlabeled image.

Restarting from scratch:

Use `--restart` to clear previously labeled copies (in `processed/.../situation` and `processed/.../normal`) and begin again from the very first screenshot without touching the original `screenshots/` source images:

```powershell
python label_screenshots.py --ticker BTCUSDT --interval 15m --time "1 month" --restart
```

## Future Ideas

* Add exchange selection (Binance Futures, Bybit, etc.)
* Add output to Parquet
* Add plotting / screenshot generation

---
Feel free to extend this script further; open an issue or adapt it for additional workflows.
