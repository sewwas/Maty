import time
from typing import Dict, List, Optional

class PAMMMasterPool:
    """
    Manages institutional PAMM Master Pool state bound to Exness MT5 Account 433909448.
    """
    def __init__(self, master_account: int = 433909448):
        self.master_account = int(master_account)
        self.total_aum = 1266.34
        self.investors_count = 42
        self.master_win_rate = 94.2
        self.avg_monthly_yield = 18.5
        self.max_drawdown_limit = 4.5
        
        self.investor_portfolio = {
            "account_id": str(master_account),
            "deposited_amount": 1000.0,
            "current_equity": 1266.34,
            "total_profit": 266.34,
            "roi_pct": 26.63,
            "share_pct": 100.0,
            "join_date": "2026-01-15"
        }
        
        self.deposit_withdraw_history: List[dict] = [
            {"type": "DEPOSIT", "amount": 1000.0, "timestamp": time.time() - 86400 * 30, "status": "COMPLETED"},
            {"type": "PROFIT_PAYOUT", "amount": 266.34, "timestamp": time.time() - 86400 * 7, "status": "COMPLETED"}
        ]

    def configure_account(self, account_num: int, initial_deposit: float):
        """Dynamically configures and binds a target MT5 account to the PAMM pool."""
        self.master_account = int(account_num)
        self.investor_portfolio["account_id"] = str(account_num)
        if initial_deposit > 0:
            self.investor_portfolio["deposited_amount"] = float(initial_deposit)
            dep = float(initial_deposit)
            curr = self.investor_portfolio["current_equity"]
            self.investor_portfolio["total_profit"] = float(curr - dep)
            self.investor_portfolio["roi_pct"] = float(((curr - dep) / dep) * 100.0)

    def sync_live_equity(self, live_equity: float):
        """Syncs PAMM Pool AUM directly from Exness MT5 Account 433909448 equity."""
        if live_equity > 0:
            self.total_aum = float(live_equity)
            self.investor_portfolio["current_equity"] = float(live_equity)
            dep = self.investor_portfolio["deposited_amount"]
            if dep > 0:
                self.investor_portfolio["total_profit"] = float(live_equity - dep)
                self.investor_portfolio["roi_pct"] = float(((live_equity - dep) / dep) * 100.0)
        
    def distribute_pnl(self, net_pnl: float):
        """Distributes trading engine profits to Total AUM and investor portfolios."""
        if net_pnl == 0.0:
            return
        self.total_aum += net_pnl
        user_share = (self.investor_portfolio["share_pct"] / 100.0) * net_pnl
        self.investor_portfolio["current_equity"] += user_share
        self.investor_portfolio["total_profit"] += user_share
        dep = self.investor_portfolio["deposited_amount"]
        if dep > 0:
            self.investor_portfolio["roi_pct"] = (self.investor_portfolio["total_profit"] / dep) * 100.0

    def process_deposit(self, amount: float) -> bool:
        if amount <= 0:
            return False
        self.total_aum += amount
        self.investor_portfolio["deposited_amount"] += amount
        self.investor_portfolio["current_equity"] += amount
        self.investor_portfolio["share_pct"] = (self.investor_portfolio["current_equity"] / self.total_aum) * 100.0
        self.deposit_withdraw_history.append({
            "type": "DEPOSIT",
            "amount": amount,
            "timestamp": time.time(),
            "status": "COMPLETED"
        })
        return True

    def process_withdrawal(self, amount: float) -> bool:
        if amount <= 0 or amount > self.investor_portfolio["current_equity"]:
            return False
        self.total_aum -= amount
        self.investor_portfolio["current_equity"] -= amount
        self.investor_portfolio["share_pct"] = (self.investor_portfolio["current_equity"] / self.total_aum) * 100.0
        self.deposit_withdraw_history.append({
            "type": "WITHDRAWAL",
            "amount": amount,
            "timestamp": time.time(),
            "status": "COMPLETED"
        })
        return True
