# 🏛️ MATY AI QUANTITATIVE FUND
## Document 02: Quantitative Architecture & Risk Shield Specifications

---

### Overview

This technical specification document details the core algorithmic components of the **Maty AI Execution Engine**.

---

## 1. The 4 Synchronized Dynamic Engines

### A. Dynamic Target Profit Engine
$$\text{Universal Exit Floor} = \text{Friction Floor (Spread + Commission + Swap)} + \max\left(\$1.00,\, \$1.00 \times \text{Volume Scale Multiplier}\right)$$
* **Guarantee**: Every single profit exit rule is hard-locked to require net cash profit after ALL broker fees are paid.

### B. Pure Dynamic Risk & Basket-Scaled Stop Loss Engine
$$\text{Dynamic Stop Loss} = \text{Account Equity} \times 10\% \times \left(1.0 + (N_{\text{fills}} - 1) \times 0.25\right)$$
* **Guarantee**: 0.0 hardcoded stop loss limits. Risk scales dynamically with account balance and open basket volume.

### C. Dynamic Auto-Compounding Lot Sizing Engine
$$\text{Base Order Size} = \text{Base Size} \times \max\left(0.50,\, \frac{\text{Account Equity}}{\$1,000}\right) \times \text{Confidence Score}$$
* **Guarantee**: Order sizes scale automatically as equity grows, enabling hands-free profit compounding.

### D. Session-Aware Volatility Geometry Engine
* 🌏 **Asian Session (23:00 – 07:00 GMT)**: 1.30x gap multiplier (absorbs low-liquidity range drift).
* 🏛️ **London / NY Overlap (12:00 – 16:00 GMT)**: 0.85x gap multiplier (captures fast breakout velocity).

---

## 2. Advanced Risk Management & Safety Features

1. 🛡️ **Dynamic Counter-Hedge Reversal Lock**: Automatically deploys counter-hedge orders on parabolic trend drawdowns, converting single-side risk into a market-neutral hedged basket.
2. 📊 **Orderbook Pressure Imbalance Filter**: Pauses trap deployment into 75%+ institutional sell/buy walls.
3. 🌊 **Live Spread-Noise Filter**: Trap offsets dynamically scale to 2.5x live broker spread during rollover hours.
4. ⏱️ **Friday Weekend Shutdown Guard**: Pauses grid deployment 2 hours before Friday market close to eliminate weekend gap risk.
