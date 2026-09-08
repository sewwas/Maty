"""
Bot #3 — Performance & Quantitative Analytics Module
=====================================================
Calculates:
- Realized Win Rate %
- Profit Factor (PF)
- Gross Profit / Gross Loss / Net Realized P&L
- Expectancy & Average Win/Loss Payoff Ratio
- Consecutive Win/Loss Streaks
- Cumulative Profit & Equity Curve
"""

from typing import List, Dict, Any
import datetime


def calculate_performance_metrics(deals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes professional quantitative performance statistics from reconstructed closed deals.
    Deals are assumed to be sorted in reverse-chronological order (newest first) or chronological.
    """
    if not deals:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "breakeven_trades": 0,
            "win_rate": 0.0,
            "loss_rate": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "net_profit": 0.0,
            "profit_factor": 0.0,
            "profit_factor_label": "N/A (No Trades)",
            "avg_trade": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "payoff_ratio": 0.0,
            "expectancy": 0.0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "total_volume": 0.0,
            "equity_curve": []
        }

    # Sort chronological (oldest to newest) for cumulative equity calculation
    sorted_deals = sorted(deals, key=lambda x: x.get("_close_timestamp", 0))

    wins = []
    losses = []
    breakevens = []
    total_volume = 0.0

    cumulative_pnl = 0.0
    equity_curve = []

    # Initial baseline point
    if sorted_deals:
        first_t = sorted_deals[0].get("open_time", "")
        equity_curve.append({
            "trade_num": 0,
            "time": first_t or "Start",
            "pnl": 0.0,
            "cumulative_pnl": 0.0
        })

    current_win_streak = 0
    max_win_streak = 0
    current_loss_streak = 0
    max_loss_streak = 0

    for idx, d in enumerate(sorted_deals, start=1):
        pnl = float(d.get("net_pnl", 0.0))
        vol = float(d.get("volume", 0.0))
        total_volume += vol
        cumulative_pnl += pnl

        equity_curve.append({
            "trade_num": idx,
            "time": d.get("close_time", f"Trade #{idx}"),
            "pnl": round(pnl, 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "side": d.get("side", "BUY"),
            "ticket": d.get("ticket", "")
        })

        if pnl > 0.001:
            wins.append(pnl)
            current_win_streak += 1
            current_loss_streak = 0
            if current_win_streak > max_win_streak:
                max_win_streak = current_win_streak
        elif pnl < -0.001:
            losses.append(pnl)
            current_loss_streak += 1
            current_win_streak = 0
            if current_loss_streak > max_loss_streak:
                max_loss_streak = current_loss_streak
        else:
            breakevens.append(pnl)
            current_win_streak = 0
            current_loss_streak = 0

    total_count = len(sorted_deals)
    win_count = len(wins)
    loss_count = len(losses)
    be_count = len(breakevens)

    win_rate = (win_count / total_count * 100.0) if total_count > 0 else 0.0
    loss_rate = (loss_count / total_count * 100.0) if total_count > 0 else 0.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net_profit = gross_profit - gross_loss

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
        if profit_factor >= 2.5:
            pf_label = f"{profit_factor:.2f} (Elite)"
        elif profit_factor >= 1.75:
            pf_label = f"{profit_factor:.2f} (Excellent)"
        elif profit_factor >= 1.25:
            pf_label = f"{profit_factor:.2f} (Profitable)"
        elif profit_factor >= 1.0:
            pf_label = f"{profit_factor:.2f} (Break-Even)"
        else:
            pf_label = f"{profit_factor:.2f} (Underperforming)"
    else:
        if gross_profit > 0:
            profit_factor = 99.99
            pf_label = "∞ (100% Win Ratio)"
        else:
            profit_factor = 0.0
            pf_label = "0.00"

    avg_win = (gross_profit / win_count) if win_count > 0 else 0.0
    avg_loss = (gross_loss / loss_count) if loss_count > 0 else 0.0
    avg_trade = (net_profit / total_count) if total_count > 0 else 0.0

    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else 0.0)

    # Expectancy = (Win_Rate * Avg_Win) - (Loss_Rate * Avg_Loss)
    p_win = win_count / total_count if total_count > 0 else 0.0
    p_loss = loss_count / total_count if total_count > 0 else 0.0
    expectancy = (p_win * avg_win) - (p_loss * avg_loss)

    return {
        "total_trades": total_count,
        "winning_trades": win_count,
        "losing_trades": loss_count,
        "breakeven_trades": be_count,
        "win_rate": round(win_rate, 1),
        "loss_rate": round(loss_rate, 1),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_profit": round(net_profit, 2),
        "profit_factor": profit_factor,
        "profit_factor_label": pf_label,
        "avg_trade": round(avg_trade, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "payoff_ratio": round(payoff_ratio, 2),
        "expectancy": round(expectancy, 2),
        "max_consecutive_wins": max_win_streak,
        "max_consecutive_losses": max_loss_streak,
        "total_volume": round(total_volume, 2),
        "equity_curve": equity_curve
    }
