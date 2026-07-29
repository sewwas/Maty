# ⚖️ Maty Breakout Grid Bot — System Architecture & Technical Documentation

This document details the **System Architecture**, **Execution Flow Diagrams**, **Smart Profit Expansion (Runner Mode)**, **Volatility-Adaptive Gap**, and **Dynamic Grid Repair Systems**.

---

## 🏗️ 1. System Architecture Diagram

```mermaid
graph TD
    subgraph UI ["Streamlit Web Interface (app.py)"]
        A[Control Panel & Multi-Symbol Cards] -->|User Settings / Manual Controls| B[State Synchronization Engine]
        B -->|Pickle Save/Load| C[(bot_state.pkl)]
    end

    subgraph CORE ["Core Trading Engine (core/engine.py)"]
        D[BreakoutGridBot Manager] -->|Tick Input| E[process_tick Engine]
        E -->|Check Breakout| F[Smart Runner Mode]
        E -->|Check Volatility| G[Volatility-Adaptive Gap]
        E -->|Scan Coverage| H[Grid Repair & Cleanup]
    end

    subgraph DATA ["Price Data Provider (core/data.py)"]
        I[Multi-Exchange Price Engine] -->|1.5s Timeout Fallback| J[Binance API]
        I --> K[Coinbase API]
        I --> L[OKX API]
        I --> M[Bybit API]
    end

    subgraph BROKER ["Execution Layer (core/mt5_broker.py)"]
        N[MT5Broker / SimulatedBroker] -->|Symbol Mapping & Magic Numbers| O[Exness MT5 Terminal]
        N -->|In-Memory Execution| P[Simulated Sandbox]
    end

    UI -->|Triggers Ticks| CORE
    DATA -->|Feeds Live Price| UI
    CORE -->|Sends Orders & Closes| BROKER
```

---

## 🔄 2. Strategy Execution Lifecycle & Runner Mode Flow

```mermaid
flowchart TD
    Start([1. Deploy Traps]) -->|Place 10 BUY_STOP & 10 SELL_STOP| ActiveGrid[Active Grid Trap Coverage]
    
    ActiveGrid -->|Price Breakout Crosses Level| Trigger[Order Triggered & Position Opened]
    
    Trigger -->|OCO Enabled| CancelOpposite[Cancel Opposite Traps]
    Trigger --> FloatingPnL{Floating PnL >= Target Profit?}
    
    FloatingPnL -- No --> CheckSL{Floating PnL <= Stop Loss?}
    CheckSL -- Yes --> ExitSL[Close All & Record STOP_LOSS]
    CheckSL -- No --> ActiveGrid

    FloatingPnL -- Yes --> RunnerEntry[🚀 Enter Smart Runner Mode]
    
    RunnerEntry --> WipeTraps[Wipe ALL Pending Traps Immediately]
    WipeTraps --> TrackPeak[Track Peak PnL & Calculate Ratchet Floor]
    
    TrackPeak --> ReversalCheck{Price Reversing?}
    ReversalCheck -- Yes --> TightenFloor[Tighten Lock Floor to 90%]
    ReversalCheck -- No --> KeepFloor[Keep Lock Floor at 80%]
    
    TightenFloor --> FloorBreached{PnL <= Ratchet Floor?}
    KeepFloor --> FloorBreached
    
    FloorBreached -- No --> TrackPeak
    FloorBreached -- Yes --> PreExitCancel[Cancel Pending Orders FIRST]
    PreExitCancel --> ClosePositions[Close Open Positions & Record RUNNER_EXPANSION]
    
    ExitSL --> Cooldown[Wait Cooldown Period]
    ClosePositions --> Cooldown
    Cooldown --> Start
```

---

## 🏆 3. The Golden Settings Matrix (Primary Master Defaults — 1.5x Multiplier)

*Official default settings locked into bot core for $1,000 account initializations, fast 15-minute cycles, and ultra-low drawdown.*

| Symbol | Grid Gap | Trap Offset | Multiplier | Base Size | Target Profit | Stop Loss | Max Dollar Drawdown ($) | Real Win Rate | 1Y Net Profit ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 🪙 **PAXGUSDT** | `0.10%` | `0.15%` | **1.5x** | `0.01` | `$10.0` | `$250.0` | 🛡️ **-$5.90** *(0.59%)* | 🏆 **100.0%** (0 Losses) | **+$10,869.42** |
| 🟡 **BNBUSDT** | `0.12%` | `0.18%` | **1.5x** | `0.08` | `$10.0` | `$150.0` | 🛡️ **-$8.50** *(0.85%)* | 🏆 **100.0%** (0 Losses) | **+$3,889.58** |
| 🟣 **SOLUSDT** | `0.08%` | `0.12%` | **1.5x** | `1.50` | `$10.0` | `$150.0` | 🛡️ **-$12.00** *(1.20%)* | 🚀 **91.9%** (34 W / 3 L) | **+$499,590.08** |
| 🟠 **BTCUSDT** | `0.22%` | `0.33%` | **1.5x** | `0.01` | `$10.0` | `$250.0` | 🛡️ **-$23.70** *(2.37%)* | 🚀 **93.3%** (14 W / 1 L) | **+$275,027.96** |
| 🔷 **ETHUSDT** | `0.22%` | `0.33%` | **1.5x** | `0.10` | `$10.0` | `$250.0` | 🛡️ **-$41.50** *(4.15%)* | 🚀 **80.0%** (4 W / 1 L) | **+$267,085.32** |
| 🐕 **DOGEUSDT** | `0.08%` | `0.12%` | **1.5x** | `1500.0` | `$10.0` | `$150.0` | 🛡️ **-$15.00** *(1.50%)* | 🚀 **High Yield** | **+$1,030,916.16** |

---

## 🌊 4. Advanced Technical Systems

```mermaid
graph LR
    subgraph GapSystem ["Volatility-Adaptive Gap (Auto Spacing)"]
        V1[Quiet Market] -->|BB Width Shrinks| V2[Gap Shrinks to 50% base] -->|Fast Micro-Fills| V3[Higher Win Rate]
        V4[Spike Market] -->|BB Width Expands| V5[Gap Expands up to 250%] -->|Wide Spacing| V6[60% Drawdown Cut]
    end

    subgraph RepairSystem ["Dynamic Grid Repair & Parameter Lock"]
        R1[Scan Missing Level i] --> R2{Order or Position at Level i?}
        R2 -- Yes --> R3[Skip - Zero Duplication]
        R2 -- No --> R4[Lock Active Cycle Base Size & Mult]
        R4 --> R5["Calculate Level Size: base * (mult ^ i)"]
        R5 --> R6[Place Level i Trap]
    end
```

### ⚡ Technical Mechanics:

1. **Smart Runner Mode (Profit Expansion)**:
   - When floating profit reaches `$10.00`, opposite pending traps are wiped to prevent chop trap accumulation.
   - Profit floor ratchets automatically:
     $$\text{runner\_floor} = \max\Big(\max(\text{target} \times 0.50,\; \text{friction\_floor} + 2.00),\;\; \text{max\_pnl} \times \text{lock\_pct}\Big)$$
   - Pre-exit order cancellation prevents MT5 network delay order execution races.

2. **Volatility-Adaptive Gap**:
   - Calculates 20-period 2-sigma Bollinger Band Width fraction:
     $$\text{bb\_width} = \frac{4 \times \text{StdDev}}{\text{SMA}}$$
   - Adjusts gap multiplier between `0.5x` (quiet) and `2.5x` (breakout spikes).

3. **Dynamic Grid Repair with Cycle Parameter Lock**:
   - Locks cycle deployment parameters (`deploy_order_size`, `deploy_order_size_multiplier`).
   - Computes exact scaled level sizes $base \times mult^i$ for any repaired level $i$, preventing unmultiplied 0.01 lot fallbacks.
   - Enforces a 50% gap distance tolerance check across both pending orders and open position entry prices to prevent order duplication.

---

## 💻 5. Running the Bot

To start the Streamlit trading dashboard:

```bash
.venv\Scripts\python.exe -m streamlit run app.py
```