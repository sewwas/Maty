"""
Bot #4 Analytics Engine — SMC Liquidity Hunter
Calculates institutional performance metrics, win rates, profit factor, and drawdowns.
"""

from typing import Dict, List, Any


def calculate_performance_metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_profit": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "avg_rr": 0.0,
            "max_drawdown": 0.0
        }

    total_trades = len(trades)
    wins = 0
    losses = 0
    gross_profit = 0.0
    gross_loss = 0.0
    net_profit = 0.0
    rr_list = []
    
    cumulative_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0

    for t in trades:
        pnl = float(t.get("pnl", 0.0))
        net_profit += pnl
        cumulative_pnl += pnl

        if cumulative_pnl > peak_pnl:
            peak_pnl = cumulative_pnl
        dd = peak_pnl - cumulative_pnl
        if dd > max_dd:
            max_dd = dd

        if pnl > 0.01:
            wins += 1
            gross_profit += pnl
            rr = float(t.get("rr", 0.0))
            if rr > 0:
                rr_list.append(rr)
        elif pnl < -0.01:
            losses += 1
            gross_loss += abs(pnl)

    win_rate = round((wins / total_trades) * 100.0, 1) if total_trades > 0 else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    avg_rr = round(sum(rr_list) / len(rr_list), 2) if rr_list else 0.0

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "net_profit": round(net_profit, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": profit_factor,
        "avg_rr": avg_rr,
        "max_drawdown": round(max_dd, 2)
    }
