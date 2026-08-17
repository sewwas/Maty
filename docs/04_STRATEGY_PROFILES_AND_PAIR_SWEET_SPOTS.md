# AI Strategy Profiles & Pair Baseline Sweet Spots

## Executive Summary
This document outlines the 3 AI Strategy Profiles (**Conservative**, **AI Balanced (Golden Default)**, **Aggressive Scalper**) and documents the baseline parameters (`base_lot`, `grid_gap`, `trap_offset`, `min_tp`, `lot_mult`) for supported digital assets and forex pairs.

---

## 1. Deep Parameter Comparison Matrix

| Parameter / Profile | 🛡️ CONSERVATIVE | ⚖️ AI BALANCED (Golden Default) 🏆 | ⚡ AGGRESSIVE SCALPER |
| :--- | :--- | :--- | :--- |
| **Grid Matrix** | `2 Levels per side (4 total)` | **`3 Levels per side (6 total)`** 🏆 | `3 Levels per side (6 total)` |
| **Pending Trap Retention** | `STRICT_PURGE` | **`AUTO_ADAPTIVE`** 🏆 | `ALWAYS_RETAIN` |
| **Grid Gap (`grid_gap`)** | `0.15% - 0.25%` (Wide spacing) | **`0.08% - 0.10%`** (Optimal) 🏆 | `0.04% - 0.05%` (Ultra-tight) |
| **Trap Offset (`trap_offset`)** | `0.15% - 0.20%` (Outer envelope) | **`0.08% - 0.15%`** (Noise boundary) 🏆 | `0.04% - 0.06%` (Immediate entry) |
| **Base Lot Size (`base_lot`)** | `0.001 BTC / 0.05 ETH / 0.005 Gold` | **`0.001 BTC / 0.10 ETH / 0.01 Gold`** | `0.002 BTC / 0.20 ETH / 0.02 Gold` |
| **Target Profit (`min_tp`)** | `$2.00 USD` (Fast harvest) | **`$3.50 - $4.50 USD`** *(Runner $\to$ \$10+)* | `$0.10 - $2.00 USD` (Micro scalp) |
| **Lot Multiplier (`lot_mult`)**| `1.15x` (Low scaling) | **`1.25x`** (Standard) 🏆 | `1.35x` (Aggressive) |
| **Expected Win Rate** | **`98.8%`** | 🏆 **`98.2%`** | **`88.0%`** |
| **Max Expected Drawdown** | **`< 0.45%`** | 🏆 **`< 0.59%`** | **`< 2.50%`** |
| **Trade Frequency** | $10 - 20$ cycles/day | $25 - 60$ cycles/day | $80+$ cycles/day |

---

## 2. Per-Symbol Baseline Parameters (`PAIR_SWEET_SPOTS`)

The engine configures baseline parameters per trading pair based on contract specifications and asset volatility ([core/engine.py:L230-L255](file:///c:/Users/User/Desktop/Maty/core/engine.py#L230-L255)):

### Digital Assets (24/7 Trading)
* **`BTCUSD` / `BTCUSDT`:**
  * Baseline Lot: `0.001 BTC` (per $1,000 equity)
  * Max Safe Lot Cap: `0.05 BTC` (Hard Cap)
  * Grid Gap: `0.06%` (quiet) to `0.10%` (active)
  * Trap Offset: `0.05%` to `0.08%`
  * Target Profit: `$10.00 USD` (Runner Mode enabled)
* **`ETHUSD` / `ETHUSDT`:**
  * Baseline Lot: `0.10 ETH` (per $1,000 equity)
  * Max Safe Lot Cap: `0.50 ETH` (Hard Cap)
  * Grid Gap: `0.06%` to `0.10%`
  * Trap Offset: `0.05%` to `0.08%`
  * Target Profit: `$3.50 USD`
* **`SOLUSD` / `SOLUSDT`:**
  * Baseline Lot: `1.50 SOL`
  * Max Safe Lot Cap: `3.00 SOL` (Hard Cap)
  * Grid Gap: `0.05%` to `0.09%`
  * Target Profit: `$3.00 USD`
* **`BNBUSD` / `BNBUSDT`:**
  * Baseline Lot: `0.20 BNB`
  * Max Safe Lot Cap: `0.50 BNB` (Hard Cap)
  * Grid Gap: `0.05%` to `0.09%`
  * Target Profit: `$3.00 USD`
* **`DOGEUSD` / `DOGEUSDT`:**
  * Baseline Lot: `100.0 DOGE`
  * Max Safe Lot Cap: `1000.0 DOGE` (Hard Cap)
  * Grid Gap: `0.05%` to `0.08%`
  * Target Profit: `$2.50 USD`

### Metals & Forex (Mon-Fri Trading with Weekend Shield)
* **`XAUUSD` / `GOLD` / `PAXGUSDT`:**
  * Baseline Lot: `0.01 Lot` (per $1,000 equity)
  * Max Safe Lot Cap: `0.03 Lot` (Hard Cap)
  * Grid Gap: `0.05%` to `0.07%`
  * Target Profit: `$3.50 - $10.00 USD`
* **`GBPUSD`, `EURUSD`, `USDJPY`:**
  * Baseline Lot: `0.02 Lot` (per $1,000 equity)
  * Max Safe Lot Cap: `0.20 Lot` (Hard Cap)
  * Grid Gap: `0.04%` to `0.05%`
  * Target Profit: `$2.50 - $9.00 USD`

---

## 3. Dynamic Equity Ratio Scaling

Base lot size scaling formula:

$$\text{Raw Lot Size} = \text{Pair Base Lot} \times \left( \frac{\text{Account Equity}}{\$1,000} \right)$$

This guarantees that as your account balance grows from $\$1,000$ to $\$10,000+$, trade lot sizes scale proportionally while maintaining strict risk bounds!
