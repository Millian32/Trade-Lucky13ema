# Trade-Lucky13ema
Trading view strategy and python code

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