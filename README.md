# Candle to Screenshot Utilities

This repository provides utilities to download and visualize historical OHLC (candlestick) data for:

* Crypto spot markets (Binance public REST API)
* Forex pairs (via Yahoo Finance through `yfinance`)

## Files

* `download_ohlc.py` – Pull OHLC data (crypto via Binance or forex via Yahoo Finance) for a symbol / interval / time range and save to `data/`.
* `generate_screenshots.py` – Generates sequential candlestick PNG images from previously downloaded (or freshly refreshed) data.
* `label_screenshots.py` – Interactive directional (Buy/Sell) trade labeling UI producing processed/ folder structure and statistics.
* `check_labeled_screenshots.py` – Side‑by‑side trade reviewer that pairs each closed trade's entry and exit screenshots with candle details and PnL.
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

Run the script specifying ticker, interval, time range, and optional data source. The output filename is generated automatically:

```powershell
# Crypto (Binance)
python download_ohlc.py --ticker BTCUSDT --interval 15m --time "1 month" --source binance

# Forex (Yahoo Finance via yfinance) e.g. GBPUSD 15m last month
python download_ohlc.py --ticker GBPUSD --interval 15m --time "1 month" --source forex
```

Forex symbols: provide a 6‑letter pair (e.g. EURUSD, GBPUSD, USDJPY). The tool automatically maps it to the Yahoo Finance format (e.g. `GBPUSD=X`). You may also pass an explicit Yahoo ticker (e.g. `EURUSD=X`).

This creates (examples) files like:

```
# Crypto
data/BTCUSDT_15m_1month_spot.csv

# Forex
data/GBPUSD_15m_1month_fx.csv
```

Pattern: `data/<TICKER>_<INTERVAL>_<TIMERANGE>_<suffix>.csv` where `<suffix>` is `spot` for Binance or `fx` for forex.  
Example: `BTCUSDT_15m_1month_spot.csv`, `GBPUSD_15m_1month_fx.csv`.

The `<TIMERANGE>` part removes spaces and lowercases (e.g. `1 month` -> `1month`, `3 Days` -> `3days`). If you rerun with the same parameters the file will be overwritten.

### Supported Intervals

The same interval tokens are accepted for both sources (`1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M`). For forex, `1M` is internally mapped to Yahoo's `1mo`.

### Forex Notes & Limitations

* Volume data from Yahoo Finance for many FX pairs is absent or zero; stored as `0` (synthetic) for compatibility.
* Close time is approximated as `open_time + interval_delta`; exact broker session boundaries may differ.
* Yahoo Finance free feed may throttle frequent requests; consider caching or longer intervals for large backfills.
* If you need true tick volume or broker‑specific feeds, integrate a dedicated FX data provider instead.

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

## VS Code Launch Configurations and `--source`

The provided `.vscode/launch.json` now includes both crypto (Binance spot) and forex (Yahoo Finance) presets. Each scripted workflow (download, generate, label, check) has:

* A default Binance configuration (e.g. BTCUSDT 15m 1 month)
* A default Forex configuration (e.g. GBPUSD 15m 1 month)
* An input‑driven configuration where you can pick `ticker`, `interval`, `timeRange`, `source`, and for generation also `skipCandles` / `maxCandles`.

Important: Always set the `--source` to match the dataset you want. The filename suffix (`_spot` vs `_fx`) depends on this, so downstream scripts (screenshots, labeling, trade checking) will look for the correct CSV. If you accidentally download as forex and then run label with `--source binance`, it will not locate the `_fx` file (a legacy unsuffixed fallback is only attempted in screenshot generation for backward compatibility with older datasets).

Added launch entries (examples):

* Download OHLC: Defaults GBPUSD 15m 1 month (Forex)
* Generate Screenshots: Defaults GBPUSD 15m 1 month max 96 (Forex)
* Label Screenshots: Defaults GBPUSD 15m 1 month (Forex)
* Check Trades: Defaults GBPUSD 15m 1 month (Forex)

To switch a custom (Inputs) configuration from crypto to forex, pick `forex` in the new `source` pick list when the debug panel prompts for inputs.

Rationale for explicit `--source`:

* Avoids accidental mixing of forex vs crypto datasets with similar tickers.
* Enables future extension to additional sources (e.g. futures) without breaking naming.
* Makes reproducibility explicit in logs and debug launch history.

If you need to regenerate an older dataset (pre‑suffix) you can still use screenshot generation with the same parameters; it will fall back to the legacy unsuffixed filename if the suffixed file is absent.

## Manual Labeling UI (Directional Buy/Sell Trades)

The labeling interface now supports full directional trade annotation with separate Buy and Sell entries and their corresponding exits, plus neutral ("Next") frames. It also computes key trade statistics live.

### Folder Schema

For a given (ticker, interval, time range) a processed directory is created:

```
processed/<TICKER>_<INTERVAL>_<TIMERANGE>/
	normal/      # Neutral / context frames (no event) or mid-trade continuation
	buy/         # Entry screenshots for long (BUY) trades
	buy_exit/    # Exit screenshots closing BUY trades
	sell/        # Entry screenshots for short (SELL) trades
	sell_exit/   # Exit screenshots closing SELL trades
```

Exactly one trade (either BUY or SELL) can be open at a time. Intervening frames while a trade is open should be labeled with `Next` (goes to `normal/`).

### UI Buttons & States

Initial (no open trade):
* Buy (green) – records entry in `buy/`
* Sell (red) – records entry in `sell/`
* Next (gray) – records neutral frame in `normal/`

When a BUY trade is open:
* Buy button converts to `Exit (Buy)` (yellow) – records exit in `buy_exit/`
* Sell disabled
* Next continues adding neutral frames to `normal/`

When a SELL trade is open:
* Sell button converts to `Exit (Sell)` (yellow) – records exit in `sell_exit/`
* Buy disabled
* Next continues adding neutral frames to `normal/`

### Keyboard Shortcuts

* Up Arrow = Buy / Exit (Buy)
* Down Arrow = Sell / Exit (Sell)
* Right Arrow = Next (neutral)
* Backspace = Back (undo last atomic action)
* Escape = Quit

### Status Bar

Displays only: `candle_XXXXX.png current/total` (e.g. `candle_01234.png 1234/2400`). No extra narration is added so the filename is uncluttered.

### Trade Table & Statistics

The right panel lists each trade with columns:
`Side | Entry Date | Entry Price | Exit Date | Exit Price | Result`

Result (PnL) calculation:
* BUY: `exit_price - entry_price`
* SELL: `entry_price - exit_price`

Live statistics (closed trades only):
* Number of trades
* Net Profit/Loss
* Win/Loss count and ratio
* Profit Factor (gross profit / gross loss, ∞ if no losses)

### Resume Behavior

On startup the application:
1. Scans all five processed subfolders.
2. Reconstructs each trade by pairing entries with the next chronological matching exit on the same side.
3. Determines if a trade is currently open (unmatched entry).
4. Rebuilds an internal synthetic history so the Back (undo) button works uniformly for resumed sessions.

The next unlabeled screenshot (first filename not present in any processed subfolder) becomes the current image.

### Undo Logic

`Back` performs a single atomic undo:
* If the last action was an entry: removes the entry file and deletes the row from the trade table.
* If the last action was an exit: removes the exit file and reverts the trade to open (clears exit columns).
* If the last action was a neutral frame: deletes the neutral file only.
* Index position moves back one image so you can re-label immediately.

During resumed sessions this behavior is consistent because the synthetic history mimics original labeling order.

### Running the Labeler

```powershell
python label_screenshots.py --ticker BTCUSDT --interval 15m --time "1 month"
```

If source screenshots do not exist they are generated first (same defaults as `generate_screenshots.py`: `--skip 480`, `--max-candles 96`). Use `--refresh` to re-download OHLC data before generation.

### Restarting From Scratch

Use `--restart` to delete previously labeled copies (`normal/`, `buy/`, `buy_exit/`, `sell/`, `sell_exit/`) without touching the original `screenshots/` directory:

```powershell
python label_screenshots.py --ticker BTCUSDT --interval 15m --time "1 month" --restart
```

### Data & Index Mapping

Screenshot filenames (`candle_#####.png`) are 1‑based; they map deterministically to the underlying dataframe row indices (converted to 0‑based internally). The generation process begins at `skip + 1`, so screenshot `candle_00481.png` corresponds to dataframe index `480` when the default skip (480) is used.

### Limitations / Notes

* Only one open trade side at a time is supported (no overlapping long & short positions).
* Deleting files manually from processed folders while the app is closed can desynchronize trade reconstruction (run `--restart` or re-label to correct).
* Neutral frames are not distinguished between “in-trade continuation” and “no trade” states—both go into `normal/`.
* Undo does not span across sessions beyond what can be inferred from existing files; a persistent event log could be added later.

---

### Example Processed Layout (Directional)

```
processed/
	BTCUSDT_15m_1month/
		normal/
			candle_00482.png
			...
		buy/
			candle_00510.png
			...
		buy_exit/
			candle_00525.png
			...
		sell/
			candle_00600.png
			...
		sell_exit/
			candle_00618.png
			...
```

## Future Ideas

* Redo stack / forward navigation
* Persistent event log (JSON) to allow perfect reconstruction beyond filename inference
* Per-side aggregated statistics & equity curve plotting
* Optional color coding of trade table rows (win/loss coloring)
* CSV/Parquet export of labeled events and trades
* Multi-exchange data sources (Futures, Bybit, etc.)
* ML pipeline integration scripts (dataset manifest generation)
* Filtering / search in trade table

---
Feel free to extend this script further; open an issue or adapt it for additional workflows.

---

## Trade Screenshot Checker (`check_labeled_screenshots.py`)

After you have labeled trades using `label_screenshots.py`, you can visually audit each CLOSED trade with a compact viewer that presents the entry and exit images side by side plus precise candle and PnL data.

### What It Does

* Reconstructs all CLOSED trades by scanning:
	* `processed/.../buy/` + `buy_exit/`
	* `processed/.../sell/` + `sell_exit/`
* Pairs each entry with the next chronological exit on the same side (entries lacking an exit are skipped as open / incomplete trades).
* Displays:
	* Left: Entry screenshot
	* Right: Exit screenshot
	* Trade header with index (e.g. `Trade 3/17  BUY  candle_00510.png -> candle_00525.png`)
	* Candle metadata for entry & exit (timestamp + O/H/L/C/V) extracted from the original OHLC dataframe
	* Result (PnL): BUY = exit - entry; SELL = entry - exit

### UI & Navigation

* Buttons: `Back` (previous trade), `Next` (next trade)
* Keyboard: Left Arrow = Back, Right Arrow = Next, Escape = Quit
* Buttons are disabled automatically at the beginning/end of the trade list
* If no closed trades are found a clear message is shown and navigation is disabled

### Usage

```powershell
python check_labeled_screenshots.py --ticker BTCUSDT --interval 15m --time "1 month"
```

Optional:

* `--refresh` – Re-fetch OHLC CSV before loading (ensures candle details align if you regenerated data)

### When to Use It

* Post‑label QA: verify that entries/exits reflect intended patterns
* Rapid visual sanity check before exporting data to a model pipeline
* Reviewing edge cases (very fast reversals, long holds, etc.) without re-running the full labeling UI

### Limitations

* Only shows trades with both entry and exit (open trades are ignored)
* Assumes naming convention `candle_#####.png` aligns 1‑to‑1 with dataframe rows (same as the labeling tool)
* If processed folders are manually altered (files moved/deleted) pairing accuracy can degrade; re-run the labeler if needed

### Future Enhancements (Potential)

* Include open (unclosed) trades in a separate pass
* Export reviewed trades with an approval flag
* Aggregate statistics (distribution histograms, per-side performance) inside the viewer
* Filtering by side (BUY only / SELL only) or by min/max holding length

---
