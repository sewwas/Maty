import json
import time
import logging
from bridge_client import Bot6BridgeClient
from strategy import StrategyEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("bot6.main")

def load_config():
    with open("config.json", "r") as f:
        return json.load(f)

def run():
    config = load_config()
    client = Bot6BridgeClient(magic_number=config["magic_number"])
    
    if not client.is_healthy():
        logger.error("Bridge is not running. Start start_bridges.bat first!")
        return
        
    for sym in config["symbols"]:
        client.enable_symbol(sym)
        
    engine = StrategyEngine(config["strategy_params"])
    
    tf_map = {
        "1M": "1m",
        "5M": "5m",
        "15M": "15m"
    }
    bridge_tf = tf_map.get(config["timeframe"], "1m")
    
    logger.info(f"Bot 6 (Crossfire + WVPPP) Started. Monitoring {config['symbols']} on {config['timeframe']}")
    
    try:
        while True:
            for symbol in config["symbols"]:
                df = client.get_candles(symbol, bridge_tf, limit=300)
                if df.empty:
                    continue
                    
                result = engine.analyze(df)
                
                if result["signal"] != 0:
                    tick = client.get_tick(symbol)
                    if not tick:
                        continue
                        
                    lot = config["risk_management"]["lot_size"]
                    action = "BUY" if result["signal"] == 1 else "SELL"
                    price = tick["ask"] if result["signal"] == 1 else tick["bid"]
                    
                    sl_pips = config["risk_management"]["default_sl_pips"]
                    tp_pips = config["risk_management"]["default_tp_pips"]
                    
                    # Approximated point for forex
                    point = 0.00001 if "JPY" not in symbol else 0.001
                    
                    if config["risk_management"]["use_dynamic_sl"] and "sl" in result:
                        sl = result["sl"]
                    else:
                        sl = price - (sl_pips * point * 10) if result["signal"] == 1 else price + (sl_pips * point * 10)
                        
                    tp = price + (tp_pips * point * 10) if result["signal"] == 1 else price - (tp_pips * point * 10)
                    
                    client.open_trade(
                        symbol=symbol,
                        action=action,
                        volume=lot,
                        stop_loss=sl,
                        take_profit=tp,
                        comment="3-Signal FVG+POC"
                    )
            
            time.sleep(5)
            
    except KeyboardInterrupt:
        logger.info("Stopping bot...")
    # client.shutdown() is not needed for bridge client

if __name__ == "__main__":
    run()
