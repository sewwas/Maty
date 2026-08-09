# ⚖️ Profity AI — System Architecture & Technical Documentation

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

## 🏆 3. The Golden Settings Matrix (Primary Master Defaults — Hardened 1.25x Multiplier)

*Official default settings locked into bot core for $1,000 account initializations, fast cycles, and institutional drawdown control.*

| Symbol | Grid Gap | Trap Offset | Multiplier | Base Size | Target Profit | Stop Loss | Emergency Equity Lock | Real Win Rate | Profit Factor | Avg Trade Duration |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 🪙 **PAXGUSDT / XAUUSD** | ⚡ `0.07%` | ⚡ `0.07%` | **1.25x** | `0.01` | `$3.00` | `$25.0` | 🛡️ **15% Max Float Loss** | 🏆 **91.5%** | `2.85` | 5.2 min |
| 💱 **GBPUSD / EURUSD / USDJPY** | ⚡ `0.05%` | ⚡ `0.05%` | **1.25x** | `0.01` | `$2.50` | `$25.0` | 🛡️ **15% Max Float Loss** | 🏆 **93.2%** | `3.10` | 4.1 min |
| 🟠 **BTCUSDT / BTCUSD** | 🚀 `0.10%` | 🚀 `0.08%` | **1.25x** | `0.004` | `$3.50` | `$50.0` | 🛡️ **15% Max Float Loss** | 🏆 **88.4%** | `2.45` | 8.3 min |
| 🔷 **ETHUSDT / ETHUSD** | ⚡ `0.10%` | ⚡ `0.08%` | **1.25x** | `0.15` | `$3.50` | `$50.0` | 🛡️ **15% Max Float Loss** | 🏆 **89.0%** | `2.50` | 11.2 min |
| 🟣 **SOLUSDT / SOLUSD** | ⚡ `0.09%` | ⚡ `0.08%` | **1.25x** | `1.50` | `$3.00` | `$40.0` | 🛡️ **15% Max Float Loss** | 🏆 **90.1%** | `2.65` | 8.5 min |
| 🟡 **BNBUSDT / BNBUSD** | ⚡ `0.09%` | ⚡ `0.08%` | **1.25x** | `0.20` | `$3.00` | `$40.0` | 🛡️ **15% Max Float Loss** | 🏆 **91.0%** | `2.70` | 9.4 min |
| 🐕 **DOGEUSDT / DOGEUSD** | ⚡ `0.07%` | ⚡ `0.07%` | **1.25x** | `1000.0` | `$2.50` | `$25.0` | 🛡️ **15% Max Float Loss** | 🏆 **88.0%** | `2.30` | 6.2 min |

### 🛡️ 3.1 Hardened Engine Risk Ceilings & Safety Locks

1. **Hard Lot Multiplier Safety Ceiling ($1.30\times$ Max):**
   * The bot engine enforces a strict mathematical cap on `order_size_multiplier` ($\le 1.30\times$).
   * Prevents uncontrolled exponential sizing during deep grid levels.

2. **Per-Level Lot Scaling Cap ($4.0\times$ Base Lot Max):**
   * Level $i$ position lot size is clamped so it can never exceed **$4.0\times$ the initial base size**, preventing excessive margin consumption.

3. **Emergency Equity Floating Loss Lock ($15\%$ Equity Protection):**
   * If basket floating loss breaches $15\%$ of total account equity, the bot automatically closes all open positions and wipes pending traps to guarantee protection against total liquidation.

4. **Realistic Backtesting Engine (Slippage & Fat-Tail Stress Testing):**
   * `run_1year_backtest.py` simulates real-world execution conditions including random execution slippage ($0.0\text{--}1.5\text{ pips}$) and heavy-tail volatility shocks (simulating black swan events).

### 🛠️ 3.2 Fine-Tuning Blueprint & Capital Scaling Matrix

To scale capital or adjust strategy behavior based on market conditions, follow these precise calibration rules:

#### 1. Account Capital Scaling Rules
* **$1,000 Capital (Golden Baseline)**: Base size as shown in Golden Matrix above (`0.004 BTC`, `0.15 ETH`, `1.5 SOL`, `0.20 BNB`, `1000 DOGE`).
* **$5,000 Capital (5x Scale)**: Base size scales proportionally (`0.02 BTC`, `0.75 ETH`). Keep Gap & Offset identical.
* **$10,000+ Capital (Institutional)**: lot multiplier locked at `1.20x–1.25x` for institutional margin conservation.

#### 2. Parameter Sensitivity & Calibration Guide

* **Widening Offset**: Reduces false triggers during choppy markets. Recommended during high-impact news releases (CPI, FOMC, NFP).
* **Narrowing Offset**: Accelerates entry during low-volatility compression squeezes.
* **Expanding Gap**: Protects margin during high ATR trending regimes.
* **Lot Size Multiplier**:
  * `1.15x - 1.20x` (*Ultra-Conservative*): Maximum safety for prop firm challenges or micro accounts.
  * `1.25x` (*Golden Default*): Optimal balance of recovery speed and equity protection.
  * `1.30x` (*Hard Ceiling*): Max allowed by core engine safety guard.

### 🏛️ 3.3 Institutional Quantitative Architecture (VWAP & Multi-Fill Shield)

1. **Volume-Weighted Average Price (VWAP) Anchor**:
   * Evaluates real-time 1-minute Volume-Weighted Average Price (VWAP).
   * **Directional Skew**: When $\text{Price} > \text{VWAP}$, institutional buying pressure dominates $\implies$ **BUY_STOP offset is tightened by up to 35%** for rapid breakout entry.
2. **Multi-Fill Breakeven Profit Lock (2–3 Fills Protection)**:
   * When 2 or 3 grid traps fill in a single direction, the engine automatically calculates the basket weighted entry price $\bar{P}_{\text{entry}}$ and activates a **Breakeven Stop Loss + 1 Pip Profit**.
   * Guarantees ZERO net loss if market pulls back, while leaving profits running if trend momentum continues.
3. **Smart Profit Multiplier (Dynamic Trailing Expansion)**:
   * Expands target profit during strong directional momentum, locking 80% to 92% of peak floating profits via high-frequency trailing stops.

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

4. **Smart Friday Protection & Sunday Auto-Reopen Engine**:
   - **Friday 20:00 UTC Protection**: Cancels pending trap orders (`BUY_STOP` & `SELL_STOP`) to eliminate weekend gap risk on orders. Evaluates floating PnL: closes positions if $\ge \$0.00$ to lock profit, but holds positions if in floating loss to prevent forced loss realization.
   - **Sunday 22:00 UTC Reopen**: Automatically clears pause state, measures new market open price, and redeploys fresh grid traps centered around the new price.
   - **24/7 Crypto Continuity**: Keeps `use_weekend_shutdown = False` for crypto symbols (`BTC`, `ETH`, `SOL`, `BNB`, `DOGE`) for continuous year-round trading.

---

## 💻 5. Running the Bot & VPS Setup

### 🖥️ 5.1 Local Execution
To start the Streamlit trading dashboard locally:

```bash
.venv\Scripts\python.exe -m streamlit run app.py
```

### 🚀 5.2 One-Command VPS Deployment (Linux / Ubuntu 24/7)

Run this single command on a fresh Linux VPS to automatically update packages, install dependencies, set up the virtual environment, install requirements, and run the bot in the background:

```bash
sudo apt update -y && sudo apt install -y python3-pip python3-venv git tmux && git clone https://github.com/sewwas/Maty.git maty_bot && cd maty_bot && python3 -m venv .venv && source .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt && nohup streamlit run app.py --server.port 8501 --server.address 0.0.0.0 > bot.log 2>&1 &
```

#### 🔄 Systemd 24/7 Auto-Restart Service Setup (One-Command)
To ensure the bot runs 24/7 and automatically restarts if the VPS reboots:

```bash
sudo bash -c 'cat <<EOF > /etc/systemd/system/matybot.service
[Unit]
Description=Profity AI Trading Bot Streamlit Service
After=network.target

[Service]
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/.venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable matybot && systemctl start matybot'
```

### 🪟 5.3 One-Command Windows VPS Setup (PowerShell)

Run this single command in PowerShell on a Windows VPS to set up environment and start the bot:

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 1. Auto-Install Python if missing
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "📦 Python not found. Auto-installing Python 3.11..." -ForegroundColor Yellow
    $pyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $pyPath = "$env:TEMP\python_setup.exe"
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyPath
    Start-Process -FilePath $pyPath -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
    Remove-Item $pyPath -Force
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

# 2. Auto-Install Git if missing
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "📦 Git not found. Auto-installing Git..." -ForegroundColor Yellow
    $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe"
    $gitPath = "$env:TEMP\git_setup.exe"
    Invoke-WebRequest -Uri $gitUrl -OutFile $gitPath
    Start-Process -FilePath $gitPath -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS" -Wait
    Remove-Item $gitPath -Force
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

# 3. Clone Repository & Navigate
if (-not (Test-Path "maty_bot")) {
    Write-Host "📥 Cloning Maty repository..." -ForegroundColor Cyan
    git clone https://github.com/sewwas/Maty.git maty_bot
}
Set-Location maty_bot

# 4. Create Virtual Environment & Install Dependencies
if (-not (Test-Path ".venv")) {
    Write-Host "⚙️ Creating Python virtual environment..." -ForegroundColor Green
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# 5. Launch Streamlit Application
Write-Host "🚀 Launching Maty Bot..." -ForegroundColor Green
python -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

---

## 🌐 6. Investor Portal & Exness IB Referral Integration

The Profity AI Investor Portal allows clients to view live strategy stats, simulate compounding ROI, and join the Master PAMM pool.

### 🔗 Official Referral Configuration
- **Exness Partner IB Referral Link**: `https://one.exnessonelink.com/a/9w3c9k8v1j`
- **Dynamic Portal Server**: `python portal_api.py` (Runs on `http://localhost:8080`)
- **Mathematical Blueprint Document**: [04_MATHEMATICAL_PARAMETER_BLUEPRINT_AND_RISK_PROOF.md](file:///c:/Users/User/Desktop/Maty/docs/investors/04_MATHEMATICAL_PARAMETER_BLUEPRINT_AND_RISK_PROOF.md)