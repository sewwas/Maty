import MetaTrader5 as mt5
import pandas as pd
from mt5_client import MT5Client
from strategy import StrategyEngine
import json
import logging

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

def run_backtest():
    config = load_config()
    client = MT5Client(magic_number=123)
    
    if not client.connect():
        print("Failed to connect to MT5 for backtesting.")
        return
        
    symbol = "XAUUSD"
    client.enable_symbol(symbol)
    
    # Fetch 5000 bars (~3.5 days on 1M)
    print(f"Fetching historical data for {symbol}...")
    df = client.get_ohlcv(symbol, mt5.TIMEFRAME_M1, count=5000)
    
    if df.empty:
        print("No data fetched. Check MT5 connection.")
        client.shutdown()
        return
        
    engine = StrategyEngine(config["strategy_params"])
    
    print(f"Starting backtest on {len(df)} bars of {symbol} 1M data...")
    
    trades = []
    active_trade = None
    
    sl_pips = config["risk_management"]["default_sl_pips"]
    tp_pips = config["risk_management"]["default_tp_pips"]
    
    sym_info = mt5.symbol_info(symbol)
    if not sym_info:
        print(f"Failed to get info for {symbol}")
        client.shutdown()
        return
        
    point = sym_info.point
    sl_dist = sl_pips * point * 10
    tp_dist = tp_pips * point * 10
    
    lookback = config["strategy_params"]["volume_profile_lookback"]
    
    # Suppress strategy logs during backtest to avoid console spam
    logging.getLogger("bot6.strategy").setLevel(logging.WARNING)
    
    for i in range(lookback, len(df)):
        # We simulate passing time by providing a growing window up to a limit
        window = df.iloc[max(0, i - 300):i].copy()
        window.reset_index(drop=True, inplace=True)
        
        current_bar = df.iloc[i-1]
        
        # Manage active trade
        if active_trade:
            if active_trade['type'] == 'BUY':
                if current_bar['low'] <= active_trade['sl']:
                    active_trade['status'] = 'LOSS'
                    trades.append(active_trade)
                    active_trade = None
                    continue
                elif current_bar['high'] >= active_trade['tp']:
                    active_trade['status'] = 'WIN'
                    trades.append(active_trade)
                    active_trade = None
                    continue
            elif active_trade['type'] == 'SELL':
                if current_bar['high'] >= active_trade['sl']:
                    active_trade['status'] = 'LOSS'
                    trades.append(active_trade)
                    active_trade = None
                    continue
                elif current_bar['low'] <= active_trade['tp']:
                    active_trade['status'] = 'WIN'
                    trades.append(active_trade)
                    active_trade = None
                    continue
        
        # Look for new signals
        if not active_trade:
            result = engine.analyze(window)
            if result["signal"] != 0:
                price = current_bar['close']
                
                if result["signal"] == 1:
                    sl = result.get("sl", price - sl_dist)
                    # Enforce minimum SL distance
                    if (price - sl) < (sl_dist * 0.5):
                        sl = price - sl_dist
                    tp = price + tp_dist
                    active_trade = {'type': 'BUY', 'entry': price, 'sl': sl, 'tp': tp, 'time': current_bar['time']}
                elif result["signal"] == -1:
                    sl = result.get("sl", price + sl_dist)
                    if (sl - price) < (sl_dist * 0.5):
                        sl = price + sl_dist
                    tp = price - tp_dist
                    active_trade = {'type': 'SELL', 'entry': price, 'sl': sl, 'tp': tp, 'time': current_bar['time']}
                    
    client.shutdown()
    
    print("\n--- Backtest Results ---")
    wins = len([t for t in trades if t['status'] == 'WIN'])
    losses = len([t for t in trades if t['status'] == 'LOSS'])
    total = len(trades)
    
    print(f"Total Trades: {total}")
    if total > 0:
        print(f"Wins: {wins} ({(wins/total)*100:.2f}%)")
        print(f"Losses: {losses} ({(losses/total)*100:.2f}%)")
    else:
        print("No trades taken. Strategy conditions might be too strict.")

if __name__ == "__main__":
    run_backtest()
