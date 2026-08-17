# 🔌 MetaTrader 5 & Exness Broker Integration Manual (`core/mt5_broker.py`)

## 1. Executive Summary

The [`core/mt5_broker.py`](file:///c:/Users/User/Desktop/Maty/core/mt5_broker.py) module serves as the primary hardware interface between **Maty Quantitative Grid Bot** and **MetaTrader 5 (Exness Real / Demo Servers)**. It handles zero-latency order placement, real-time pending order purges, position tracking, hardware SL/TP synchronization, and 180-day deal history parsing.

---

## 2. Core Architecture & Classes

### 2.1 `MT5Broker` Class
- **Purpose:** Connects directly to the MetaTrader 5 terminal process via official `MetaTrader5` Python API bindings.
- **Key Attributes:**
  - `pending_orders`: Active `BUY_STOP` and `SELL_STOP` breakout traps.
  - `open_positions`: Live open positions tracked by magic number.
  - `closed_trades`: Realized trade log synchronized with MT5 deal history.
  - `magic_number`: Unique symbol-bound identifier preventing cross-pair order collisions.

### 2.2 `SimulatedBroker` Class
- **Purpose:** High-performance paper-trading broker for offline strategy evaluation and demo testing without requiring a running MT5 terminal instance.

---

## 3. Order Placement & Fallback Tiers

### 3.1 3-Tier Order Filling Fallbacks
When submitting orders to Exness MT5 servers, the broker automatically cycles through filling modes if a specific filling mode is rejected:
1. **Primary Filling Mode:** Evaluated dynamically from `symbol_info.filling_mode` (`ORDER_FILLING_FOK`, `ORDER_FILLING_IOC`, or `ORDER_FILLING_RETURN`).
2. **Tier 1 Fallback:** Retries order placement with `ORDER_FILLING_RETURN`.
3. **Tier 2 Breakout Conversion:** If a limit order is rejected by broker account rules, converts to a valid `BUY_STOP` or `SELL_STOP` breakout trap.

---

## 4. Hardware SL/TP Envelopes & Noise Buffers

Every order placed on MetaTrader 5 includes explicit hardware Take Profit (`tp`) and Stop Loss (`sl`) levels calculated relative to the exact trigger price:

| Symbol Category | Hardware Stop Loss (SL) Buffer | Hardware Take Profit (TP) Buffer |
| :--- | :--- | :--- |
| **`BTCUSDT` / Bitcoin** | `$1,200.00` | `$1,800.00` |
| **`XAUUSD` / Gold** | `$35.00` | `$50.00` |
| **`ETHUSDT` / Ethereum** | `$80.00` | `$120.00` |
| **`EURUSD`, `GBPUSD`** | `0.0200` (200 pips) | `0.0300` (300 pips) |

---

## 5. Precise Price-Level Duplicate Purge

To prevent broker order stacking:
- `purge_duplicate_mt5_orders()` scans active pending orders and deduplicates them by exact price level (`(type, round(price_open, 2))`).
- It purges only true duplicate orders placed at identical prices while preserving distinct breakout grid levels ($i=0, 1, 2, 3, 4$).
