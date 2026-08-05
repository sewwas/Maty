/**
 * Profity AI — 100% Dynamic Investor Portal Engine
 * Real-time API integration with Maty bot_state.pkl engine, live performance matrix, & portfolio management.
 */

let currentMonthlyYield = 0.185; // Updated dynamically from live stats

document.addEventListener('DOMContentLoaded', () => {
    initRoiCalculator();
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

        // Live Trade Execution Feed
        updateLiveTradeFeed(stats.recent_feed);

        // Dynamic Golden Performance Matrix Table
        updatePerformanceMatrix(stats.symbols_matrix);

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

function updateLiveTradeFeed(recentTrades) {
    const feed = document.getElementById('liveTickerFeed');
    if (!feed || !recentTrades || recentTrades.length === 0) return;

    feed.innerHTML = '';
    recentTrades.forEach(trade => {
        const item = document.createElement('div');
        item.className = 'ticker-item';
        const isWin = trade.pnl >= 0;
        item.innerHTML = `
            <span class="symbol">${trade.symbol}</span>
            <span class="trade-type buy">${trade.reason}</span>
            <span class="profit" style="color: ${isWin ? '#10B981' : '#EF4444'}">${isWin ? '+' : ''}$${trade.pnl.toFixed(2)}</span>
            <span class="time">${formatTimeAgo(trade.time)}</span>
        `;
        feed.appendChild(item);
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
 * 3. INTERACTIVE ROI CALCULATOR ENGINE (DYNAMIC YIELD)
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
    };

    if (depositSlider && durationSlider) {
        depositSlider.addEventListener('input', window.updateRoiCalculator);
        durationSlider.addEventListener('input', window.updateRoiCalculator);
        compoundCheck.addEventListener('change', window.updateRoiCalculator);
        window.updateRoiCalculator();
    }

    const calcInvestCta = document.getElementById('calcInvestCta');
    if (calcInvestCta) {
        calcInvestCta.addEventListener('click', () => openModal());
    }
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
