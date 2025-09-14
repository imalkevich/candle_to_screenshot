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

The labeling tool now supports simple position life‑cycle tagging (Situation -> Exit) in addition to normal context classification.

Concepts:
* A Situation (formerly Yes) marks the start of a position.
* While a position is open, you can label interim frames as Continue (formerly No) until an Exit event occurs.
* An Exit explicitly closes the last open Situation.
* The UI enforces exactly one open position at a time: after a Situation you must Exit before opening a new one.

Folders created under `processed/`:
* `situation/` – Frames where a position is opened.
* `continue` (still stored as `normal/` on disk for compatibility) – Frames during an open position (or ordinary background when no position is open). Internally we continue to write to `normal/` for simplicity.
* `exit/` – Frames where a position is closed.

Button / State Behavior:
* Initial state (no open position): Buttons show `Yes (Situation)` and `No (Normal)`.
	* Press Yes: screenshot copied to `situation/`, state switches to "open position".
* Open position state: Buttons change to `Exit` (yellow) and `Continue` (red).
	* Press Continue: screenshot copied to `normal/` (position remains open).
	* Press Exit: screenshot copied to `exit/`, position closes; buttons revert to initial state.

Resume Logic:
* On startup the tool inspects counts: if `len(situation) > len(exit)` it assumes a position is still open and starts in Exit/Continue mode.
* Undo (Backspace or Back button) removes the last file AND reverts state transitions (opening or closing) when appropriate.

Keyboard Shortcuts:
* Enter = Primary action (Situation OR Exit depending on state)
* Space = Secondary action (Normal OR Continue depending on state)
* Backspace = Undo last action / state change
* Escape = Quit

The prior left/right arrow bindings were removed to reduce accidental mislabels.

Run:

```powershell
python label_screenshots.py --ticker BTCUSDT --interval 15m --time "1 month"
```

Example folder layout produced:

```
processed/
	BTCUSDT_15m_1month/
		situation/
			candle_00481.png
			...
		normal/
			candle_00482.png
			...
		exit/
			candle_00510.png
			...
```

If screenshots are not present, they are generated first using the same defaults (`--skip 480`, `--max-candles 96`). Use `--refresh` to force a fresh CSV download prior to generation if needed.

You can safely close the UI mid-session; on restart it will continue from the first unlabeled image.

Restarting from scratch:

Use `--restart` to clear previously labeled copies (situation / normal / exit) and begin again from the very first screenshot without touching the original `screenshots/` source images:

```powershell
python label_screenshots.py --ticker BTCUSDT --interval 15m --time "1 month" --restart
```

## Future Ideas

* Add exchange selection (Binance Futures, Bybit, etc.)
* Add output to Parquet
* Add plotting / screenshot generation

---
Feel free to extend this script further; open an issue or adapt it for additional workflows.
