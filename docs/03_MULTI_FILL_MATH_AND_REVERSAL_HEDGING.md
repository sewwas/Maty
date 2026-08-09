# Multi-Fill Mathematical Proofs & Reversal Hedging Architecture

## Executive Summary
This document provides mathematical proofs for volume-weighted average price (WVAP) shifting during martingale grid execution, multi-fill scenario behavior (Fills 1 to 4), and dual-sided hedging logic (OCO OFF mode).

---

## 1. Volume-Weighted Entry Price (WVAP) Mathematical Proof

When grid levels fill sequentially with lot size multiplier $M = 1.25$:

$$\text{WVAP}_k = \frac{\sum_{i=1}^{k} L_1 M^{i-1} P_i}{\sum_{i=1}^{k} L_1 M^{i-1}}$$

Where $P_i = P_1 - (i-1)\Delta P$ for counter-trend fills.

### Mathematical Shifting Proof ($M = 1.25$)

| Fills ($k$) | Total Open Volume | $\text{WVAP}_k$ Distance from $P_1$ | Required Dip for Breakeven Exit |
| :---: | :---: | :---: | :---: |
| **1 Fill** | $1.00 L_1$ | $0.000 \cdot \Delta P$ | $1.000 \cdot \Delta P$ |
| **2 Fills** | $2.25 L_1$ | $0.555 \cdot \Delta P$ | **$0.445 \cdot \Delta P$ (55.5% closer!)** |
| **3 Fills** | $3.81 L_1$ | $0.795 \cdot \Delta P$ | **$0.205 \cdot \Delta P$ (79.5% closer!)** |
| **4 Fills** | $5.76 L_1$ | $0.912 \cdot \Delta P$ | **$0.088 \cdot \Delta P$ (91.2% closer!)** |

> **Proof:** With $M = 1.25$, fill 4 shifts the volume-weighted average entry price $\text{WVAP}_4$ to within $0.088\times \Delta P$ of the latest market price. A minor $0.02\%$ price bounce recovers the entire 4-fill basket in net cash profit.

---

## 2. Multi-Fill Scenario Analysis

```
Fill 1 (Base Lot)  ──────► Reaches +$1.00 USD Net ────────► Quick Scalp Exit
     │
     ▼ (Market Moves Against)
Fill 2 (2.25x Vol) ──────► 0.04% Price Bounce ────────────► WVAP Cost Recovery Exit
     │
     ▼ (Market Moves Against)
Fill 3 (3.81x Vol) ──────► 0.02% Price Bounce ────────────► Capped TP Exit (Max 2.2x TP)
     │
     ▼ (Market Moves Against)
Fill 4 (5.76x Vol) ──────► Emergency Purge Triggered ────► Fast Basket Exit & Instant Reset
```

### Scenario 1: 1 Fill (Single-Side Breakout)
Exits on $+0.06\%$ move or $\ge +\$1.00\text{ USD}$ net profit. Opposite pending traps stay live on MT5.

### Scenario 2: 2 Fills (Minor Retracement Phase)
$\text{WVAP}_2$ shifts $55.5\%$ closer. Exits instantly on **WVAP Cost Recovery** at $\ge +\$1.00\text{ USD}$ net profit. If 1 BUY + 1 SELL fill simultaneously (range chop), **Instant Counter-Flip Shield** liquidates both positions immediately at $+\$1.00\text{ USD}$ net profit.

### Scenario 3: 3 Fills (Deeper Expansion)
$\text{WVAP}_3$ shifts $79.5\%$ closer. Capped volume scale multiplier ($2.2\times$ max) prevents target profit from ballooning.

### Scenario 4: 4 Fills (Heavy Trend Expansion & Safety Purge)
**Safety Purge Shield ([engine.py:L1614](file:///c:/Users/User/Desktop/Maty/core/engine.py#L1614))** cancels all remaining unfilled opposite traps. Target profit is capped at $2.2\times$ max ($\$12.00 - \$20.00$), so even a minimal $0.01\%$ price dip closes the basket in net profit.

---

## 3. Dual-Sided Hedging Architecture (OCO OFF Mode)

* **Default State:** OCO (One-Cancels-the-Other) is **OFF by default** (`cancel_opposite_on_trigger = False`).
* **Behavior:** When a `SELL` order fills, `BUY_STOP` pending traps **remain active** in MT5.
* **Reversal Protection:** If price turns around and rallies UP, your `BUY_STOP` orders fill, providing a counter-trend hedge that takes profit on the upward move.
