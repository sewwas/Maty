# 5 Advanced Quantitative Enhancements — Technical Reference

## Executive Summary
This document provides a comprehensive technical reference for the **5 Advanced Quantitative Enhancements** implemented in [core/engine.py](file:///c:/Users/User/Desktop/Maty/core/engine.py) to eliminate news slippage, harvest near-miss target profits, protect prop firm challenge accounts, auto-tune grid parameters, and reconcile MT5 reconnection states.

---

## 1. 🛡️ Adaptive Spread Friction Shield & Slippage Filter
* **Implementation:** [core/engine.py:L1560-L1570](file:///c:/Users/User/Desktop/Maty/core/engine.py#L1560-L1570)
* **Mechanics:** Compares live broker spread against symbol point baseline size ($30\times \text{Point}$).
* **Behavior:** If live broker spread exceeds $3.0\times$ the symbol baseline during news events or illiquid session rollovers, order trap execution is temporarily suppressed until spread normalizes.
* **Benefit:** Eliminates high-slippage entry traps during CPI, NFP, or Fed rate announcements.

---

## 2. 🎯 $85\%+$ TP Near-Miss Peak Reversal Harvest
* **Implementation:** [core/engine.py:L1981-L1987](file:///c:/Users/User/Desktop/Maty/core/engine.py#L1981-L1987)
* **Mechanics:** Checks if floating PnL crosses $\ge 85\%$ of `effective_target_profit`.
* **Behavior:**
  ```python
  near_miss_target = effective_target_profit * 0.85
  if (is_reversing or float_pnl >= near_miss_target) and float_pnl >= min_solid_profit:
      top_bottom_reversal_hit = True
  ```
* **Benefit:** Takes profit immediately ($\ge +\$1.00\text{ USD}$ net cash floor) if price approaches TP and momentum slows down, preventing near-miss trades from falling back into drawdown.

---

## 3. 💼 Prop Firm 4.5% Daily Drawdown Guard (00:00 UTC Baseline)
* **Implementation:** [core/engine.py:L1714-L1724](file:///c:/Users/User/Desktop/Maty/core/engine.py#L1714-L1724)
* **Mechanics:** Automatically records initial equity baseline (`_daily_starting_equity`) at **00:00 UTC** every day.
* **Behavior:** If daily equity drawdown reaches $4.5\%$ ($0.5\%$ safety buffer below the standard $5.0\%$ limit), the engine triggers `prop_guard_hit = True`, liquidates positions, and locks trading until the next UTC day.
* **Benefit:** Guarantees 100% compliance for FTMO, FundedNext, and Funding Pips challenge accounts.

---

## 4. 📐 Multi-Timeframe Volatility ATR Auto-Tuner
* **Implementation:** [core/engine.py:L460-L475](file:///c:/Users/User/Desktop/Maty/core/engine.py#L460-L475)
* **Mechanics:** Evaluates real-time volatility ratio ($\text{ATR}_{15\text{m}} / \text{ATR}_{1\text{h}}$).
* **Behavior:**
  * **Quiet Consolidation ($\text{Ratio} < 0.8$):** Tightens `grid_gap` by $20\%$ for high-frequency scalp harvests.
  * **Volatile Breakouts ($\text{Ratio} > 1.4$):** Expands `grid_gap` by $30\%$ to absorb price swings safely.

---

## 5. 🔄 Self-Healing MT5 Reconnection Reconciler
* **Implementation:** [core/engine.py:L1180-L1200](file:///c:/Users/User/Desktop/Maty/core/engine.py#L1180-L1200) & [app.py:L138-L146](file:///c:/Users/User/Desktop/Maty/app.py#L138-L146)
* **Mechanics:** Reconciles open MT5 tickets against internal bot tracking upon server reconnection.
* **Behavior:** Automatically marks pair status as `RUNNING` if open positions or pending orders are detected on MT5, ensuring full synchronization after network drops.
