# Maty Trading Engine: Quantitative Architecture & Engine Technical Manual

## Executive Summary
The **Maty Breakout Grid Engine** is an institutional-grade, multi-asset quantitative trading system engineered for MetaTrader 5 (Exness) and digital asset markets. It combines real-time tick velocity analysis, orderbook market regime detection, volume-weighted average price (VWAP) entry shifting, and a dual-layer hardware/software protection envelope.

---

## 1. Modular Core Architecture & System Components

### 1.1 `BreakoutGridBot` Engine ([core/engine.py](file:///c:/Users/User/Desktop/Maty/core/engine.py))
The `BreakoutGridBot` class serves as the clean high-level coordinator (~464 lines) delegating heavy specialized workloads to modular sub-engines:
* **`symbol`**: Asset ticker (e.g. `BTCUSD`, `ETHUSD`, `XAUUSD`, `GBPUSD`).
* **`grid_levels`**: Number of trap orders deployed per side (default: `5`).
* **`grid_gap`**: Distance percentage between grid levels (e.g., `0.08%`).
* **`trap_offset`**: Initial buffer distance percentage from live Ask/Bid prices.
* **`order_size`**: Baseline lot size per trade (e.g. `0.004 BTC` / `0.15 ETH` / `0.01 Gold`).
* **`order_size_multiplier`**: Martingale lot expansion factor per level (default: `1.25x`).
* **`target_profit`**: Baseline cycle profit target in USD (e.g. `$3.50 - $10.00`).

### 1.2 Sub-Module Engine Ecosystem
1. **Grid Deployment Engine ([core/grid_deployment.py](file:///c:/Users/User/Desktop/Maty/core/grid_deployment.py)):**
   - Handles `deploy_traps()`, `repair_grid()`, and `cleanup_stale_grid_orders()`.
   - Executes full pre-deployment `cancel_all_orders()` order-wipe guards.
   - Evaluates 100% decisive directional choices (`BUY_ONLY`, `SELL_ONLY`, `DUAL`, `AUTO_ADAPTIVE`).
2. **Grid & Risk Engine ([core/grid_risk.py](file:///c:/Users/User/Desktop/Maty/core/grid_risk.py)):**
   - Houses `process_engine_tick()`, pip sizing calculations, lot sanitization, and breakeven ratchets.
3. **Auto-Reading Engine ([core/auto_reading.py](file:///c:/Users/User/Desktop/Maty/core/auto_reading.py)):**
   - Houses `AutoReadingEngine`, category lot-clamping (`clamp_symbol_lot_size`), regime detection, SMC / Elliott Wave confluences, and `PAIR_SWEET_SPOTS` registry.
4. **History & Self-Learning Tracker ([core/history_tracker.py](file:///c:/Users/User/Desktop/Maty/core/history_tracker.py)):**
   - Records trade outcomes, calculates rolling win-rates and profit factors, and synchronizes cycle histories.

### 1.3 `MT5Broker` Interface ([core/mt5_broker.py](file:///c:/Users/User/Desktop/Maty/core/mt5_broker.py))
Handles direct communication with the MetaTrader 5 terminal:
* **0ms Latency Hardware Order Placement:** Places `BUY_LIMIT`, `SELL_LIMIT`, `BUY_STOP`, and `SELL_STOP` orders directly on Exness servers.
* **Multi-Level Order Purge:** Enforces price-level duplicate removal while supporting full `grid_levels` pending order capacity on MT5.
* **Symbol Magic Number Generation:** Assigns unique magic numbers (`SYMBOL_MAGIC_NUMBERS`) per trading pair for multi-chart isolation.
* **Auto-Reconnection & Ticket Cache:** Automatically reconciles live broker tickets upon network recovery.

---

## 2. Dual-Layer TP & SL Protection Architecture

```
                               ┌─────────────────────────────────────────┐
                               │       Live Market Price Tick           │
                               └────────────────────┬────────────────────┘
                                                    │
                   ┌────────────────────────────────┴────────────────────────────────┐
                   ▼                                                                 ▼
┌──────────────────────────────────────┐                         ┌──────────────────────────────────────┐
│  Layer 1: Hardware Broker TP & SL    │                         │   Layer 2: Real-time Software Engine │
│  (Exness MT5 Server-side Execution) │                         │   (Python Tick-by-Tick Monitor)      │
├──────────────────────────────────────┤                         ├──────────────────────────────────────┤
│ • Placed directly on broker server   │                         │ • Quick Scalp Exits @ +$1.00 USD     │
│ • 0ms black-swan spike harvesting    │                         │ • Runner Mode 85% Trailing Lock      │
│ • Catastrophic crash protection      │                         │ • Reversal Exit 92% Peak Lock        │
└──────────────────────────────────────┘                         └──────────────────────────────────────┘
```

### Layer 1: Hardware Server Protection
Every order submitted to MT5 attaches an explicit **Hardware Take Profit** and **Hardware Stop Loss** price level:
* **Hardware TP:** Set well above the highest BUY level and well below the lowest SELL level to capture fast 0ms news wicks.
* **Hardware SL:** Set far outside the grid matrix to prevent liquidation during extreme market crashes.

### Layer 2: Real-Time Software Engine
Evaluates live price ticks inside `check_target_profit()`:
* **Quick Take Profit ($\ge +\$1.00\text{ USD}$ Net Floor):** Exits single-fill and double-fill trades as soon as net profit reaches $+\$1.00\text{ USD}$, starting a fresh cycle immediately.
* **Runner Mode (Strong Trend Expansion):** Trails peak floating profit with an **85% profit lock** to maximize trend gains.
* **Instant Reversal Lock:** Tightens to a **92% peak profit lock** or top/bottom reversal exit the moment a candle reversal is detected.

---

## 3. Execution Cycle & All-Close Reset Flow

1. **Exit Trigger:** Target profit, quick scalp, or reversal condition is met ($\ge +\$1.00\text{ USD}$).
2. **Order Purge:** `broker.cancel_all_orders()` cancels all remaining pending traps on MT5.
3. **Position Liquidation:** `broker.close_all_positions()` liquidates open positions in All-Close Mode and realizes cash profit.
4. **Instant Grid Reset:** With `auto_restart = True`, the engine measures the **new live market price** and deploys a fresh grid centered around that price with new TP and SL levels.

---

## 4. Hardware SL/TP, Multi-Timeframe (MTF) & Selective Liquidation Specifications

### 4.1 Per-Level Hardware SL/TP & Limit Order Linkage
* **Per-Level Dynamic Target Calculation:** Every grid level ($i=0, 1, 2, 3, 4, 5...$) calculates level-specific valid SL and TP targets relative to that order's exact trigger price (`buy_px` / `sell_px`), completely eliminating `Invalid SL/TP` broker rejections.
* **0ms Latency Hardware Order Placement:** Places `BUY_STOP` and `SELL_STOP` breakout momentum traps directly on Exness servers.
* **`BUY_STOP` & `SELL_STOP` Breakout Matrix:** `BUY_STOP` breakout traps trigger above Ask on bullish momentum, and `SELL_STOP` breakout traps trigger below Bid on bearish momentum for 100% full-range volatility capture.
* **Dynamic Real-Time Trailing Stop:** Real-time SL ratchets behind live market price (`current_price - trailing_dist` for BUYs, `current_price + trailing_dist` for SELLs) and updates the MT5 server via `TRADE_ACTION_SLTP`. One-way protection guarantees SL **never moves against favorable price action**.
* **Preservation Shield (`sl=None`, `tp=None`):** Updating SL alone retains existing `cur_p_tp`, and updating TP alone retains existing `cur_p_sl`, preventing accidental parameter wiping.

### 4.2 Multi-Timeframe (1m + 5m/15m) Confluence Matrix
* **Isolated Timeframe Caching:** `_HISTORICAL_KLINES_CACHE` uses `cache_key = f"{sym}_{interval}"` so 1m, 5m, and 15m candle feeds maintain independent, accurate caches.
* **100% MTF Confluence Lot Booster:** When 1m execution entry aligns with 5m (`ema_bias_5m`) and 15m (`ema_bias_15m`) trend direction, the engine automatically applies a **1.35x lot size booster** to capture strong momentum.

### 4.3 Directional Liquidation & UI Quick Action Controls
* **Directional Selective Closures:** Dedicated methods (`close_buy_positions()`, `close_sell_positions()`) allow liquidating BUY positions or SELL positions independently on MT5.
* **3-Tier Execution Resilience:** All position closures use a 3-tier filling mode fallback (`FOK` $\rightarrow$ `IOC` $\rightarrow$ `RETURN`) to guarantee 100% execution success across all broker account types (Exness Standard, Pro, Cent).
* **Dashboard UI Quick Actions:** Both global toolbar and per-symbol cards feature dedicated quick buttons: `🟢 CLOSE BUY`, `🔴 CLOSE SELL`, `🚨 FLATTEN ALL`, `🔄 RESET`, and `▶ START / ⏹ STOP`.
