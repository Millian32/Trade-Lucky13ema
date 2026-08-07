# Trade-Lucky13ema
Trading view strategy and python code

https://www.tradingview.com/script/ii4VZhUA-Lucky13ema/

🚀 Lucky13ema - 1-Min Momentum Scalper
What it is
A filtered momentum strategy built around the 13 EMA crossover on 1-minute charts. Catches clean price breaks above/below the 13 EMA with 3 quality filters to reduce noise and improve win rate.

Core Logic
BUY: First green candle closing above 13 EMA (after being below)

SELL: First red candle closing below 13 EMA (after being above)

Triple Filter System:
Volume > 20-period SMA × 1.2x (confirms conviction)
VWAP alignment (longs above VWAP, shorts below)
5-min EMA confirmation (higher timeframe bias)

How to Use
Apply to 1-min chart of liquid instruments (SPY, QQQ, IWM, major stocks)
Regular hours only recommended (9:30-4:00 ET)
Start with defaults, then optimize:
Profit Target: 1.5% | Stop Loss: 0.75% (2:1 R:R)
Volume Multiplier: 1.2x

*Toggle filters OFF first to see raw signals, then ON for quality

Key Inputs
Setting Default Purpose
Use Filters ✅ ON Master filter toggle
Volume Mult 1.2x Volume conviction threshold
Profit % 1.5% Take profit target
Stop % 0.75% Risk per trade
Trailing Stop OFF Let winners run (10pt trail)

Performance Notes
70-80% fewer signals vs raw EMA crosses
Higher win rate from multi-filter confirmation
Best on trending days, choppy markets kill it!!!!!!!!!
Backtest 6+ months before live use
Risk Management
Fixed R:R or trailing stops keep math simple
Never risk >1-2% account per trade
Avoid news events - volume spikes create false breaks

Pro Tips
SPY/QQQ best - tight spreads, high volume
Enable debug table to see filter status
2:1 R:R minimum (try 2%/1% settings)
Trail on strong movers (>3% runs)

Built for scalpers who want quality over quantity. Test thoroughly!


*Published April 30, 2026 | Optimized for 2026 market structure
May 2
Release Notes
What changed
Longs now require either close > VWAP or an actual VWAP cross, depending on the toggle.

Shorts now use the mirrored condition with close < VWAP or a VWAP cross.

I added is_red for the short side so the entry logic is more balanced and easier to reason about.

Entries are guarded by current position direction to reduce duplicate flips.

Python Auto-Trader

The Python app now supports automated signal evaluation and broker execution through a pluggable broker interface.

Files:
- Python/auto_trader.py: main loop that polls market data, evaluates strategy, and sends orders.
- Python/strategy.py: Lucky13 EMA signal engine.
- Python/broker.py: broker abstraction with `PaperBroker`, `AlpacaBroker`, and `IbkrBroker`.
- Python/config.json: strategy and broker configuration.

Quick start (paper mode):
1. `cd Python`
2. `python -m venv .venv`
3. `.venv\Scripts\activate`
4. `pip install -r requirements.txt`
5. Ensure `config.json` has `"broker": { "name": "paper" }` and `"dry_run": true`
6. `python auto_trader.py`

Risk, session, and journaling controls:
- `risk.max_drawdown_pct`: blocks new entries after portfolio drawdown breaches the limit.
- `risk.max_trades_per_day`: blocks new entries after the daily entry count is reached.
- `risk.kill_switch_file`: if this file exists, all new entries are blocked immediately.
- `market.calendar` and `market.timezone`: use exchange hours and holidays to avoid trading when the market is closed.
- `logging.path`: JSONL structured event log.
- `trade_journal.format`: `csv` or `sqlite`.

Alpaca integration:
1. In `config.json`, set `"broker": { "name": "alpaca", "paper": true }`
2. Set credentials in environment variables:
	- PowerShell: `$env:ALPACA_API_KEY="..."` and `$env:ALPACA_API_SECRET="..."`
3. For real order execution, set `"dry_run": false`
4. Run `python auto_trader.py`

IBKR integration:
1. Start TWS or IB Gateway locally.
2. In `config.json`, set `"broker": { "name": "ibkr", "host": "127.0.0.1", "port": 7497, "client_id": 1 }`
3. For paper trading, use your IBKR paper TWS or Gateway port.
4. Set `"dry_run": false` to send orders.
5. Run `python auto_trader.py`

Safety notes:
- Start with `dry_run: true` and paper accounts only.
- This sample now includes max drawdown, max trades per day, market-hours checks, a kill switch, and trade journaling, but it still needs broader production hardening.
- Test extensively before any live deployment.