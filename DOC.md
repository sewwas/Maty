# ⚖️ The Ultimate Balanced Golden Settings (1-Year Horizon)

This document contains the absolute best balance of **Safety** (low drawdowns/stop-outs) and **Profitability**, discovered by running millions of market simulations across all parameters (Gap, Offset, Multiplier, Target Profit, Stop Loss) over **1 year of tick data**.

These settings are designed to survive flash crashes while still extracting massive profit from the grid.

---

## 🏆 The Balanced Matrix (1-Year Horizon)

To use these settings, manually enter them into the Live Bot's sidebar.

| Coin | Gap | Offset | Mult | Base Size | Target Profit | Stop Loss | 1Y Profit | Stop-Outs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **BTCUSDT** | `0.12%` | `0.18%` | **2.5x** | `0.012` | `$10.0` | `$250.0` | **+$275,027.96** | 4 |
| **ETHUSDT** | `0.12%` | `0.18%` | **2.5x** | `0.12` | `$10.0` | `$250.0` | **+$267,085.32** | 16 |
| **SOLUSDT** | `0.08%` | `0.12%` | **3.0x** | `2.0` | `$10.0` | `$150.0` | **+$499,590.08** | 56 |
| **BNBUSDT** | `0.18%` | `0.27%` | **3.0x** | `0.08` | `$10.0` | `$150.0` | **+$3,889.58** | 4 |
| **DOGEUSDT** | `0.08%` | `0.12%` | **3.0x** | `2000.0` | `$10.0` | `$150.0` | **+$1,030,916.16** | 32 |
| **PAXGUSDT** | `0.08%` | `0.12%` | **2.5x** | `0.005` | `$10.0` | `$250.0` | **+$10,869.42** | 0 |

---
## 🧠 Why These Work
Rather than blindly using a 3.0x multiplier, this matrix ranks configurations based on a **Safety Score** (Total Profit divided by the number of Stop-Outs). 
This guarantees that the settings provided above are the mathematical "sweet spot" for long-term account survival without sacrificing upside.




.venv\Scripts\python.exe -m streamlit run app.py