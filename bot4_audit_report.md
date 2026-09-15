# Bot #4 (SMC Liquidity Hunter) Audit Report

## 1. Why are the trades failing (hitting Stop Loss)?

**Diagnosis: Stop Loss is too tight for XAUUSD (Gold).**
I analyzed the engine logs and the trades executed today. The Bot successfully identified Liquidity Sweeps and FVG reversals, however, all 3 trades were stopped out within minutes (losing -1.40, -1.70, and -2.80 points). 

**Root Cause:**
In `bot4_smc/smc_engine.py`, the dynamic risk management logic calculates an extremely tight Stop Loss distance.
- It tries to place the SL just 0.50 points ($0.50) above/below the sweep extreme.
- If it's too tight, a fallback sets it to a minimum of `1.50` points ($1.50).
- On Gold (XAUUSD), a $1.50 stop loss is effectively microscopic. The normal market spread and standard 5-minute volatility noise (ATR is usually $2.00-$4.00) will easily trigger a $1.50 stop loss immediately. 

**Recommendation:**
Increase the SL buffer for XAUUSD. Change the minimum fallback from `1.50` to at least `3.00` or `4.00` points in `_calculate_dynamic_smc_risk` to give the trade room to breathe.

---

## 2. Why are the Real Metrics not showing on the Hub?

**Diagnosis: Port conflict / Ghost process on the VPS.**
I checked the `bridge_8004.log` and the server's running processes. 

**Root Cause:**
- Your logs show: `[Bridge 8004] Bind attempt 1 failed: [WinError 10013] Access denied`.
- This means when you tried to start Bot #4's bridge, it failed to bind to port 8004 because an **older background instance of the bridge (`wineserver`) was already running on port 8004**.
- The Hub API *is* actually successfully pulling the `-5.90` PnL from the old ghost process (Account `184143680`, `Exness-MT5Real25`). However, because of the port conflict, any new restarts or config changes you make aren't taking effect because the old process is stubbornly holding the port.

**Recommendation:**
To fix the metrics display and ensure your latest bot settings take effect, you must kill the stuck `wineserver` process on the VPS that is hoarding port 8004:
1. Log into your VPS terminal.
2. Run `fuser -k 8004/tcp` to force-kill the ghost process.
3. Restart Bot #4 and the Hub.
