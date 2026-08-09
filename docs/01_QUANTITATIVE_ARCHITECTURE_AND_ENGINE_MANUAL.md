# Maty Trading Engine: Quantitative Architecture & Engine Technical Manual

## Executive Summary
The **Maty Breakout Grid Engine** is an institutional-grade, multi-asset quantitative trading system engineered for MetaTrader 5 (Exness) and digital asset markets. It combines real-time tick velocity analysis, orderbook market regime detection, volume-weighted average price (WVAP) entry shifting, and a dual-layer hardware/software protection envelope.

---

## 1. Core Architecture & System Components

### 1.1 `BreakoutGridBot` Engine ([core/engine.py](file:///c:/Users/User/Desktop/Maty/core/engine.py))
The `BreakoutGridBot` class orchestrates real-time price monitoring, grid trap generation, trailing profit locks, stop loss scaling, and automated cycle resets.

Key Attributes:
* `symbol`: Asset ticker (e.g. `BTCUSD`, `ETHUSD`, `XAUUSD`, `GBPUSD`).
* `grid_levels`: Number of trap orders deployed per side (default: `5`).
* `grid_gap`: Distance percentage between grid levels (e.g., `0.08%`).
* `trap_offset`: Initial buffer distance percentage from live Ask/Bid prices.
* `order_size`: Baseline lot size per trade (e.g. `0.004 BTC` / `0.15 ETH` / `0.01 Gold`).
* `order_size_multiplier`: Martingale lot expansion factor per level (default: `1.25x`).
* `target_profit`: Baseline cycle profit target in USD (e.g. `$3.50 - $10.00`).

### 1.2 `MT5Broker` Interface ([core/mt5_broker.py](file:///c:/Users/User/Desktop/Maty/core/mt5_broker.py))
Handles direct communication with the MetaTrader 5 terminal:
* **0ms Latency Hardware Order Placement:** Places `BUY_STOP` and `SELL_STOP` orders directly on Exness servers.
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
