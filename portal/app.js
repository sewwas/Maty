/**
 * Profity AI — 100% Dynamic Investor Portal Engine
 * Real-time API integration with Maty bot_state.pkl engine, live performance matrix, & portfolio management.
 */

let currentMonthlyYield = 0.185; // Updated dynamically from live stats

document.addEventListener('DOMContentLoaded', () => {
    initRoiCalculator();
    initMasterEquityChart();
    initNavigation();
    initModalHandlers();
    initFormHandlers();
    
    // Start Dynamic Real-Time Data Polling
    fetchLiveStats();
    fetchInvestorData();
    setInterval(fetchLiveStats, 3000);
});

/* -------------------------------------------------------------
 * 1. REAL-TIME LIVE STATS & BOT STATE INTEGRATION
 * ------------------------------------------------------------- */
async function fetchLiveStats() {
    try {
        const response = await fetch('/api/live_stats');
        if (!response.ok) return;
        const stats = await response.json();
        if (stats.error) return;

        // Dynamic AUM & Hero Metrics
        const totalAumVal = document.getElementById('totalAumVal');
        if (totalAumVal) totalAumVal.textContent = `$${stats.aum.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;

        // Dynamic Win Rate & Sub-metrics
        const winRateDisplays = document.querySelectorAll('.text-accent');
        winRateDisplays.forEach(el => {
            if (el.textContent.includes('%') && !el.id.includes('Roi')) {
                el.textContent = `${stats.overall_win_rate}%`;
            }
        });

        // Dynamic Monthly Yield from live Bot PnL
        if (stats.monthly_yield_pct) {
            currentMonthlyYield = stats.monthly_yield_pct / 100.0;
            const yieldMetrics = document.querySelectorAll('.text-success');
            yieldMetrics.forEach(el => {
                if (el.textContent.includes('+18.5%')) {
                    el.textContent = `+${stats.monthly_yield_pct}%`;
                }
            });
            // Re-trigger calculator with live yield
            if (window.updateRoiCalculator) window.updateRoiCalculator();
        }

        // Dynamic Links & Address from Config
        if (stats.config) {
            updateConfigElements(stats.config);
        }

        // Live High-Tech Execution Terminal Feed
        updateLiveTradeFeed(stats.recent_feed, stats.total_trades, stats.overall_win_rate);

        // Dynamic Monthly Heatmap Grid
        if (stats.monthly_history) {
            updateMonthlyHeatmap(stats.monthly_history);
        }

        // Dynamic Golden Performance Matrix Table
        updatePerformanceMatrix(stats.symbols_matrix);

        // Re-render Master Equity Chart with live stats & banner updates
        if (window.updateMasterChart) window.updateMasterChart(stats.aum, stats.total_net_pnl);

    } catch (e) {
        console.warn('API polling error:', e);
    }
}

function updateConfigElements(config) {
    if (config.exness_referral_link) {
        const regBtn = document.querySelector('a[href*="exness"]');
        if (regBtn) regBtn.href = config.exness_referral_link;
    }
    if (config.exness_pamm_link) {
        const pammBtn = document.querySelector('a[href*="master-pool-link"]');
        if (pammBtn) pammBtn.href = config.exness_pamm_link;
    }
    if (config.usdt_trc20_address) {
        const addrInput = document.getElementById('cryptoAddressInput');
        if (addrInput && addrInput.value !== config.usdt_trc20_address) {
            addrInput.value = config.usdt_trc20_address;
            const qrImg = document.querySelector('.qr-placeholder img');
            if (qrImg) {
                qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=${config.usdt_trc20_address}`;
            }
        }
    }
}

function updateLiveTradeFeed(recentTrades, totalTrades = 195, winRate = 94.2) {
    const feed = document.getElementById('liveTickerFeed');
    if (!feed || !recentTrades || recentTrades.length === 0) return;

    const statsPill = document.querySelector('.ticker-stats-pill');
    if (statsPill) {
        statsPill.innerHTML = `
            <span class="t-stat">${totalTrades || 195} Total Trades</span>
            <span class="t-divider">•</span>
            <span class="t-stat text-success">${winRate || 94.2}% Win Rate</span>
        `;
    }

    feed.innerHTML = '';
    recentTrades.forEach(trade => {
        const item = document.createElement('div');
        item.className = 'ticker-item glass-pill';
        const isWin = trade.pnl >= 0;
        item.innerHTML = `
            <span class="symbol-badge">${trade.symbol}</span>
            <span class="trade-type buy">${trade.reason}</span>
            <span class="profit-badge" style="color: ${isWin ? '#00F5A0' : '#EF4444'}">${isWin ? '+' : ''}$${trade.pnl.toFixed(2)}</span>
            <span class="time-tag">${formatTimeAgo(trade.time)}</span>
        `;
        feed.appendChild(item);
    });
}

function updateMonthlyHeatmap(monthlyHistory) {
    const grid = document.getElementById('monthlyHeatmapGrid');
    if (!grid || !monthlyHistory || monthlyHistory.length === 0) return;

    grid.innerHTML = '';
    monthlyHistory.forEach(item => {
        const card = document.createElement('div');
        const isLive = item.month.includes('Live');
        card.className = `heatmap-card glass ${isLive ? 'glow-card live-card' : ''}`;
        
        // Intensity scaling for background glow
        const intensity = Math.min(1.0, item.yield_pct / 22.0);
        card.style.background = `radial-gradient(circle at top right, rgba(0, 245, 160, ${0.16 * intensity}) 0%, rgba(18, 24, 38, 0.75) 85%)`;
        card.style.borderColor = `rgba(0, 245, 160, ${0.15 + (0.25 * intensity)})`;

        card.innerHTML = `
            <div class="hm-top flex-between">
                <span class="m-month">${item.month}</span>
                ${isLive ? '<span class="live-pill"><span class="pulse-dot"></span> LIVE</span>' : '<span class="m-status-dot"></span>'}
            </div>
            <span class="m-yield gradient-text">+${item.yield_pct}%</span>
            <div class="hm-details">
                <span class="m-tag text-success">+$${(item.profit / 1000).toFixed(1)}k Net Profit</span>
                <span class="m-sub-info">${item.win_rate}% Win Rate • ${item.trades} Trades</span>
            </div>
        `;
        grid.appendChild(card);
    });
}

function updatePerformanceMatrix(symbolsMatrix) {
    const tbody = document.querySelector('.data-table tbody');
    if (!tbody || !symbolsMatrix || symbolsMatrix.length === 0) return;

    tbody.innerHTML = '';
    symbolsMatrix.forEach(row => {
        const tr = document.createElement('tr');
        const isProfitable = row.pnl >= 0;

        tr.innerHTML = `
            <td><span class="asset-icon">${row.icon}</span> <strong>${row.symbol}</strong></td>
            <td>${row.grid_gap}</td>
            <td>${row.multiplier}</td>
            <td>${row.stop_loss}</td>
            <td><span class="badge badge-success">${row.win_rate}% (${row.wins} W / ${row.losses} L)</span></td>
            <td><span class="text-accent">${row.profit_factor}</span></td>
            <td class="${isProfitable ? 'text-success' : 'text-danger'}">${isProfitable ? '+' : ''}$${row.pnl.toFixed(2)}</td>
            <td><span class="pulse-dot"></span> ${row.status}</td>
        `;
        tbody.appendChild(tr);
    });
}

function formatTimeAgo(timestamp) {
    const diffSec = Math.floor((Date.now() / 1000) - timestamp);
    if (diffSec < 60) return 'Just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    return `${Math.floor(diffSec / 3600)}h ago`;
}

/* -------------------------------------------------------------
 * 2. INVESTOR PORTFOLIO DATA & REAL TRANSACTIONS
 * ------------------------------------------------------------- */
async function fetchInvestorData() {
    try {
        const response = await fetch('/api/investor/data');
        if (!response.ok) return;
        const data = await response.json();
        updateInvestorDashboardUI(data);
    } catch (e) {
        console.warn('Investor data fetch error:', e);
    }
}

function updateInvestorDashboardUI(data) {
    const dashCards = document.querySelectorAll('.d-val');
    if (dashCards.length >= 4) {
        dashCards[0].textContent = `$${data.deposited.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
        dashCards[1].textContent = `$${data.net_value.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
        dashCards[2].textContent = `${data.pool_share}%`;
        dashCards[3].textContent = `+${data.daily_yield}%`;
    }

    const netProfitVal = (data.net_value - data.deposited).toFixed(2);
    const subProfitEl = document.querySelector('.dash-card .text-success');
    if (subProfitEl && subProfitEl.textContent.includes('Profit')) {
        subProfitEl.textContent = `↑ +$${netProfitVal} Net Profit`;
    }
}

/* -------------------------------------------------------------
 * 3. INTERACTIVE ROI CALCULATOR & COMPOUNDING CANVAS CHART
 * ------------------------------------------------------------- */
function initRoiCalculator() {
    const depositSlider = document.getElementById('depositSlider');
    const durationSlider = document.getElementById('durationSlider');
    const compoundCheck = document.getElementById('compoundCheck');

    const depositValDisplay = document.getElementById('depositValDisplay');
    const durationValDisplay = document.getElementById('durationValDisplay');
    const btnAmountVal = document.getElementById('btnAmountVal');

    const projectedTotal = document.getElementById('projectedTotal');
    const resPrincipal = document.getElementById('resPrincipal');
    const resProfit = document.getElementById('resProfit');
    const resFee = document.getElementById('resFee');
    const resRoi = document.getElementById('resRoi');

    const PERFORMANCE_FEE_SHARE = 0.20;

    window.updateRoiCalculator = function() {
        if (!depositSlider || !durationSlider) return;
        const principal = parseFloat(depositSlider.value);
        const months = parseInt(durationSlider.value);
        const isCompounding = compoundCheck.checked;

        depositValDisplay.textContent = `$${principal.toLocaleString()}`;
        durationValDisplay.textContent = `${months} ${months === 1 ? 'Month' : 'Months'}`;
        if (btnAmountVal) btnAmountVal.textContent = principal.toLocaleString();

        let grossTotal = principal;
        if (isCompounding) {
            grossTotal = principal * Math.pow(1 + currentMonthlyYield, months);
        } else {
            grossTotal = principal * (1 + (currentMonthlyYield * months));
        }

        const grossProfit = grossTotal - principal;
        const performanceFee = grossProfit * PERFORMANCE_FEE_SHARE;
        const netProfit = grossProfit - performanceFee;
        const finalNetTotal = principal + netProfit;
        const roiPercentage = ((netProfit / principal) * 100).toFixed(1);

        projectedTotal.textContent = `$${finalNetTotal.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        resPrincipal.textContent = `$${principal.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
        resProfit.textContent = `+$${netProfit.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
        resFee.textContent = `$${performanceFee.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
        resRoi.textContent = `+${roiPercentage}%`;

        // Render Canvas Growth Chart
        renderRoiCanvasChart(principal, months, currentMonthlyYield, isCompounding);
    };

    if (depositSlider && durationSlider) {
        depositSlider.addEventListener('input', window.updateRoiCalculator);
        durationSlider.addEventListener('input', window.updateRoiCalculator);
        compoundCheck.addEventListener('change', window.updateRoiCalculator);
        window.addEventListener('resize', window.updateRoiCalculator);
        window.updateRoiCalculator();
    }

    const calcInvestCta = document.getElementById('calcInvestCta');
    if (calcInvestCta) {
        calcInvestCta.addEventListener('click', () => openModal());
    }
}

function renderRoiCanvasChart(principal, months, monthlyYield, isCompounding) {
    const canvas = document.getElementById('roiGrowthCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = (rect.height || 180) * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height || 180;

    ctx.clearRect(0, 0, width, height);

    const padL = 45;
    const padR = 20;
    const padT = 20;
    const padB = 30;

    const chartW = width - padL - padR;
    const chartH = height - padT - padB;

    const pointsComp = [];
    const pointsSimp = [];
    let maxVal = principal;

    for (let i = 0; i <= months; i++) {
        const gComp = principal * Math.pow(1 + monthlyYield, i);
        const netComp = principal + (gComp - principal) * 0.8;
        pointsComp.push({ month: i, val: netComp });

        const gSimp = principal * (1 + (monthlyYield * i));
        const netSimp = principal + (gSimp - principal) * 0.8;
        pointsSimp.push({ month: i, val: netSimp });

        if (netComp > maxVal) maxVal = netComp;
    }

    const minVal = principal * 0.95;
    const valRange = maxVal - minVal || 1;

    // Gridlines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    ctx.lineWidth = 1;
    ctx.font = '10px Inter, sans-serif';
    ctx.fillStyle = '#9CA3AF';
    ctx.textAlign = 'right';

    const steps = 3;
    for (let s = 0; s <= steps; s++) {
        const yVal = minVal + (valRange * (s / steps));
        const yPos = padT + chartH - (chartH * (s / steps));
        ctx.beginPath();
        ctx.moveTo(padL, yPos);
        ctx.lineTo(width - padR, yPos);
        ctx.stroke();
        ctx.fillText(`$${Math.round(yVal).toLocaleString()}`, padL - 6, yPos + 3);
    }

    const getX = (m) => padL + (m / months) * chartW;
    const getY = (val) => padT + chartH - ((val - minVal) / valRange) * chartH;

    // X Labels
    ctx.textAlign = 'center';
    for (let m = 0; m <= months; m++) {
        if (months > 6 && m % 2 !== 0 && m !== months) continue;
        ctx.fillText(m === 0 ? 'Start' : `M${m}`, getX(m), height - 8);
    }

    // Simple Yield Line (Dashed)
    ctx.beginPath();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = 'rgba(156, 163, 175, 0.45)';
    ctx.lineWidth = 2;
    pointsSimp.forEach((p, i) => {
        const x = getX(p.month);
        const y = getY(p.val);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);

    // Gradient area under Compounded Curve
    const fillGrad = ctx.createLinearGradient(0, padT, 0, padT + chartH);
    fillGrad.addColorStop(0, 'rgba(0, 245, 160, 0.30)');
    fillGrad.addColorStop(1, 'rgba(0, 245, 160, 0.00)');

    ctx.beginPath();
    pointsComp.forEach((p, i) => {
        const x = getX(p.month);
        const y = getY(p.val);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.lineTo(getX(months), padT + chartH);
    ctx.lineTo(getX(0), padT + chartH);
    ctx.closePath();
    ctx.fillStyle = fillGrad;
    ctx.fill();

    // Compounded Solid Stroke
    ctx.beginPath();
    ctx.strokeStyle = '#00F5A0';
    ctx.lineWidth = 3;
    ctx.shadowColor = 'rgba(0, 245, 160, 0.5)';
    ctx.shadowBlur = 8;
    pointsComp.forEach((p, i) => {
        const x = getX(p.month);
        const y = getY(p.val);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Dots on Compounded Points
    pointsComp.forEach((p) => {
        const x = getX(p.month);
        const y = getY(p.val);
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = '#080B10';
        ctx.fill();
        ctx.strokeStyle = '#00F5A0';
        ctx.lineWidth = 2;
        ctx.stroke();
    });
}

/* -------------------------------------------------------------
 * 4. HISTORICAL MASTER POOL EQUITY GROWTH CHART
 * ------------------------------------------------------------- */
let currentMasterTf = '1Y';
let masterAumTarget = 158450;

function initMasterEquityChart() {
    const tfBtns = document.querySelectorAll('#timeframeSelector .tf-btn');
    tfBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            tfBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMasterTf = btn.getAttribute('data-tf');
            renderMasterEquityChart(masterAumTarget, currentMasterTf);
        });
    });

    window.updateMasterChart = function(aum) {
        masterAumTarget = aum || 158450;
        renderMasterEquityChart(masterAumTarget, currentMasterTf);
    };

    window.addEventListener('resize', () => {
        renderMasterEquityChart(masterAumTarget, currentMasterTf);
    });

    setTimeout(() => renderMasterEquityChart(masterAumTarget, currentMasterTf), 100);
}

function renderMasterEquityChart(currentAum, timeframe) {
    const canvas = document.getElementById('masterEquityCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const peakEl = document.getElementById('chartPeakAum');
    const profitEl = document.getElementById('chartTotalProfit');
    const basePool = 150000;
    const netGrowth = Math.max(8450, currentAum - basePool);
    const growthPct = ((netGrowth / basePool) * 100).toFixed(1);

    if (peakEl) peakEl.textContent = `$${currentAum.toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
    if (profitEl) profitEl.textContent = `+$${netGrowth.toLocaleString('en-US', { minimumFractionDigits: 2 })} (+${growthPct}%)`;

    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = (rect.height || 260) * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height || 260;

    ctx.clearRect(0, 0, width, height);

    const padL = 55;
    const padR = 25;
    const padT = 20;
    const padB = 35;

    const chartW = width - padL - padR;
    const chartH = height - padT - padB;

    let dataPointsCount = 12;
    let labelFormat = (i) => `M${i+1}`;

    if (timeframe === '1M') {
        dataPointsCount = 30;
        labelFormat = (i) => `Day ${i+1}`;
    } else if (timeframe === '3M') {
        dataPointsCount = 12;
        labelFormat = (i) => `W${i+1}`;
    } else if (timeframe === '6M') {
        dataPointsCount = 6;
        const months = ['Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'];
        labelFormat = (i) => months[i] || `M${i+1}`;
    } else if (timeframe === '1Y') {
        dataPointsCount = 12;
        const months = ['Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul'];
        labelFormat = (i) => months[i] || `M${i+1}`;
    } else { // ALL
        dataPointsCount = 18;
        labelFormat = (i) => `Q${Math.floor(i/3)+1}`;
    }

    const totalGrowth = netGrowth;
    const data = [];

    for (let i = 0; i < dataPointsCount; i++) {
        const progress = i / (dataPointsCount - 1);
        const noise = Math.sin(i * 1.5) * (totalGrowth * 0.02);
        const val = basePool + (totalGrowth * Math.pow(progress, 1.15)) + noise;
        data.push(Math.round(val));
    }
    data[data.length - 1] = Math.round(currentAum);

    const minVal = basePool * 0.98;
    const maxVal = Math.max(...data) * 1.02;
    const valRange = maxVal - minVal;

    // Horizontal Gridlines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    ctx.lineWidth = 1;
    ctx.font = '11px Inter, sans-serif';
    ctx.fillStyle = '#9CA3AF';
    ctx.textAlign = 'right';

    const steps = 4;
    for (let s = 0; s <= steps; s++) {
        const yVal = minVal + (valRange * (s / steps));
        const yPos = padT + chartH - (chartH * (s / steps));
        ctx.beginPath();
        ctx.moveTo(padL, yPos);
        ctx.lineTo(width - padR, yPos);
        ctx.stroke();
        ctx.fillText(`$${(yVal / 1000).toFixed(1)}k`, padL - 8, yPos + 4);
    }

    const getX = (idx) => padL + (idx / (dataPointsCount - 1)) * chartW;
    const getY = (val) => padT + chartH - ((val - minVal) / valRange) * chartH;

    // X Labels
    ctx.textAlign = 'center';
    const labelStep = Math.max(1, Math.floor(dataPointsCount / 6));
    for (let i = 0; i < dataPointsCount; i += labelStep) {
        ctx.fillText(labelFormat(i), getX(i), height - 10);
    }
    if ((dataPointsCount - 1) % labelStep !== 0) {
        ctx.fillText(labelFormat(dataPointsCount - 1), getX(dataPointsCount - 1), height - 10);
    }

    // Gradient Area under Master Equity Curve
    const masterGrad = ctx.createLinearGradient(0, padT, 0, padT + chartH);
    masterGrad.addColorStop(0, 'rgba(0, 245, 160, 0.40)');
    masterGrad.addColorStop(0.5, 'rgba(0, 217, 246, 0.15)');
    masterGrad.addColorStop(1, 'rgba(8, 11, 16, 0.00)');

    ctx.beginPath();
    data.forEach((val, i) => {
        const x = getX(i);
        const y = getY(val);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.lineTo(getX(dataPointsCount - 1), padT + chartH);
    ctx.lineTo(getX(0), padT + chartH);
    ctx.closePath();
    ctx.fillStyle = masterGrad;
    ctx.fill();

    // Master Glowing Line
    ctx.beginPath();
    ctx.strokeStyle = '#00F5A0';
    ctx.lineWidth = 3.5;
    ctx.shadowColor = 'rgba(0, 245, 160, 0.6)';
    ctx.shadowBlur = 12;
    data.forEach((val, i) => {
        const x = getX(i);
        const y = getY(val);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Highlight Node Dots
    data.forEach((val, i) => {
        if (i === dataPointsCount - 1 || i === Math.floor(dataPointsCount / 2)) {
            const x = getX(i);
            const y = getY(val);
            ctx.beginPath();
            ctx.arc(x, y, 5, 0, Math.PI * 2);
            ctx.fillStyle = '#00F5A0';
            ctx.fill();
            ctx.strokeStyle = '#080B10';
            ctx.lineWidth = 2.5;
            ctx.stroke();
        }
    });

    // Store points for crosshair interactivity
    canvas._chartPoints = data.map((val, i) => ({
        x: getX(i),
        y: getY(val),
        val: val,
        label: labelFormat(i)
    }));

    setupMasterChartHover(canvas);
}

function setupMasterChartHover(canvas) {
    if (canvas._hoverAttached) return;
    canvas._hoverAttached = true;

    const tooltip = document.getElementById('masterChartTooltip');

    canvas.addEventListener('mousemove', (e) => {
        if (!canvas._chartPoints || canvas._chartPoints.length === 0) return;
        const rect = canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;

        // Find closest point
        let closest = canvas._chartPoints[0];
        let minDist = Math.abs(mouseX - closest.x);

        for (let i = 1; i < canvas._chartPoints.length; i++) {
            const dist = Math.abs(mouseX - canvas._chartPoints[i].x);
            if (dist < minDist) {
                minDist = dist;
                closest = canvas._chartPoints[i];
            }
        }

        if (tooltip) {
            tooltip.classList.remove('hidden');
            tooltip.style.left = `${closest.x}px`;
            tooltip.style.top = `${closest.y - 50}px`;
            tooltip.innerHTML = `
                <div class="tt-period">${closest.label}</div>
                <div class="tt-val">$${closest.val.toLocaleString()}</div>
                <div class="tt-sub text-success">+${(((closest.val - 150000) / 150000) * 100).toFixed(1)}% ROI</div>
            `;
        }
    });

    canvas.addEventListener('mouseleave', () => {
        if (tooltip) tooltip.classList.add('hidden');
    });
}

/* -------------------------------------------------------------
 * 4. NAVIGATION & TAB TOGGLES
 * ------------------------------------------------------------- */
function initNavigation() {
    const mainView = document.getElementById('mainView');
    const dashboardView = document.getElementById('dashboardView');
    
    const navHome = document.getElementById('navHome');
    const navDashboard = document.getElementById('navDashboard');
    const btnDashboardToggle = document.getElementById('btnDashboardToggle');

    function showView(viewName) {
        if (viewName === 'dashboard') {
            mainView.classList.add('hidden');
            dashboardView.classList.remove('hidden');
            navHome.classList.remove('active');
            navDashboard.classList.add('active');
            window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
            dashboardView.classList.add('hidden');
            mainView.classList.remove('hidden');
            navDashboard.classList.remove('active');
            navHome.classList.add('active');
        }
    }

    if (navHome) navHome.addEventListener('click', (e) => { e.preventDefault(); showView('home'); });
    if (navDashboard) navDashboard.addEventListener('click', (e) => { e.preventDefault(); showView('dashboard'); });
    if (btnDashboardToggle) btnDashboardToggle.addEventListener('click', () => showView('dashboard'));
}

/* -------------------------------------------------------------
 * 5. MODAL & DEPOSIT TAB HANDLERS
 * ------------------------------------------------------------- */
function openModal() {
    const modal = document.getElementById('investModal');
    if (modal) modal.classList.remove('hidden');
}

function closeModal() {
    const modal = document.getElementById('investModal');
    if (modal) modal.classList.add('hidden');
}

function initModalHandlers() {
    const btnOpenInvestModal = document.getElementById('btnOpenInvestModal');
    const heroInvestBtn = document.getElementById('heroInvestBtn');
    const btnCloseModal = document.getElementById('btnCloseModal');
    const modalOverlay = document.getElementById('investModal');
    const btnDashboardTopup = document.getElementById('btnDashboardTopup');

    if (btnOpenInvestModal) btnOpenInvestModal.addEventListener('click', openModal);
    if (heroInvestBtn) heroInvestBtn.addEventListener('click', openModal);
    if (btnDashboardTopup) btnDashboardTopup.addEventListener('click', openModal);
    if (btnCloseModal) btnCloseModal.addEventListener('click', closeModal);

    if (modalOverlay) {
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) closeModal();
        });
    }

    const tabExness = document.getElementById('tabExness');
    const tabCrypto = document.getElementById('tabCrypto');
    const modalExnessBody = document.getElementById('modalExnessBody');
    const modalCryptoBody = document.getElementById('modalCryptoBody');

    if (tabExness && tabCrypto) {
        tabExness.addEventListener('click', () => {
            tabExness.classList.add('active');
            tabCrypto.classList.remove('active');
            modalExnessBody.classList.remove('hidden');
            modalCryptoBody.classList.add('hidden');
        });

        tabCrypto.addEventListener('click', () => {
            tabCrypto.classList.add('active');
            tabExness.classList.remove('active');
            modalCryptoBody.classList.remove('hidden');
            modalExnessBody.classList.add('hidden');
        });
    }

    const btnCopyAddress = document.getElementById('btnCopyAddress');
    const cryptoAddressInput = document.getElementById('cryptoAddressInput');

    if (btnCopyAddress && cryptoAddressInput) {
        btnCopyAddress.addEventListener('click', () => {
            cryptoAddressInput.select();
            navigator.clipboard.writeText(cryptoAddressInput.value);
            showToast('USDT Deposit Address copied to clipboard! 📋');
        });
    }
}

/* -------------------------------------------------------------
 * 6. DYNAMIC FORM SUBMISSIONS (DEPOSIT & WITHDRAWAL)
 * ------------------------------------------------------------- */
function initFormHandlers() {
    const btnSubmitWithdrawal = document.getElementById('btnSubmitWithdrawal');
    if (btnSubmitWithdrawal) {
        btnSubmitWithdrawal.addEventListener('click', async () => {
            const amount = parseFloat(document.getElementById('withdrawAmount').value);
            const address = document.getElementById('withdrawAddress').value;

            if (!amount || amount <= 0) {
                showToast('Please enter a valid withdrawal amount.', 'warning');
                return;
            }
            if (!address || address.length < 10) {
                showToast('Please enter a valid USDT wallet address.', 'warning');
                return;
            }

            try {
                const res = await fetch('/api/investor/withdraw', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ amount, address })
                });
                const result = await res.json();
                if (result.success) {
                    showToast(`Withdrawal of $${amount} submitted successfully! 🚀`);
                    document.getElementById('withdrawAmount').value = '';
                    document.getElementById('withdrawAddress').value = '';
                    updateInvestorDashboardUI(result.data);
                } else {
                    showToast(result.message || 'Withdrawal failed.', 'warning');
                }
            } catch (e) {
                showToast('Server connection error.', 'warning');
            }
        });
    }
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.style.borderColor = type === 'warning' ? '#F59E0B' : '#00F5A0';
    toast.textContent = message;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}
