"""
Bot #5 Performance Analytics & Metric Aggregator
Calculates Institutional KPIs: Sharpe Ratio, Win Rate, Profit Factor, Max Drawdown
"""

import datetime
from typing import Dict, List, Any
import numpy as np
import pandas as pd


def calculate_performance_metrics(history_deals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes standard institutional performance metrics from trade deal history.
    """
    if not history_deals:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_profit": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0
        }

    profits = []
    for d in history_deals:
        p = float(d.get("profit", 0.0))
        # Exclude balance deposits/withdrawals
        if d.get("entry") in [1, "OUT", "DEAL_ENTRY_OUT", "deal_out"] or p != 0.0:
            profits.append(p)

    if not profits:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_profit": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0
        }

    total_trades = len(profits)
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
    total_profit = sum(profits)

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.9 if gross_win > 0 else 1.0)

    # Max Drawdown calculation
    cumsum = np.cumsum(profits)
    peak = np.maximum.accumulate(cumsum)
    drawdowns = peak - cumsum
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    # Annualized Sharpe approximation
    if len(profits) > 2 and np.std(profits) > 0:
        sharpe = round(float(np.mean(profits) / np.std(profits) * np.sqrt(252)), 2)
    else:
        sharpe = 0.0

    avg_win = round(float(np.mean(wins)), 2) if wins else 0.0
    avg_loss = round(float(np.mean(losses)), 2) if losses else 0.0

    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_profit": round(total_profit, 2),
        "profit_factor": profit_factor,
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": sharpe,
        "avg_win": avg_win,
        "avg_loss": avg_loss
    }
