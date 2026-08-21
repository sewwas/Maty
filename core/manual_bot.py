import time
from typing import Optional
from core.engine import BreakoutGridBot

class ManualGridBot(BreakoutGridBot):
    """
    A separate subclass purely for manual deployments.
    This guarantees zero interference from the AutoReadingEngine or hardcoded equity limits.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_auto_reading = False
        if hasattr(self, "auto_reading_engine"):
            delattr(self, "auto_reading_engine")

    def evaluate_dynamic_grid_state(self, current_price: float, timestamp: float):
        # Auto-deploy initial grid traps on startup if not yet deployed
        if not getattr(self, "deployed", False) and current_price > 0:
            self.deploy_traps(current_price, timestamp, force=True)

    def deploy_traps(self, current_price: float, timestamp: float, *args, force: bool = False, **kwargs):
        if not current_price or current_price <= 0:
            return

        cooldown_expiry = getattr(self, "_post_loss_cooldown", 0.0)
        if timestamp < cooldown_expiry:
            return 
        
        sym_name = str(getattr(self.broker, "symbol", getattr(self, "symbol_code", "BTCUSDT"))).upper()

        if getattr(self, "_is_deploying", False):
            return

        max_capacity = (getattr(self, "grid_levels", 5) or 5) * 2
        if not force and len(getattr(self.broker, "pending_orders", {})) >= max_capacity:
            return

        self._is_deploying = True

        try:
            if force or len(getattr(self.broker, "pending_orders", {})) == 0:
                if hasattr(self.broker, "cancel_all_orders"):
                    try: self.broker.cancel_all_orders()
                    except: pass

            digits = 4 if any(x in sym_name for x in ["DOGE", "GBP", "EUR"]) else (3 if any(x in sym_name for x in ["XAU", "GOLD", "PAXG"]) else 2)
            ask_ref = getattr(self.broker, "last_ask", current_price) or current_price
            bid_ref = getattr(self.broker, "last_bid", current_price) or current_price

            if ask_ref <= 0: ask_ref = current_price
            if bid_ref <= 0: bid_ref = current_price

            # STRICTLY USE MANUAL CONFIGS
            gap_cfg = float(getattr(self, "grid_gap", 10.0))
            offset_cfg = float(getattr(self, "trap_offset", 15.0))
            effective_levels = int(getattr(self, "grid_levels", 15))

            if getattr(self, "is_percent", True):
                off_ratio = (offset_cfg / 100.0)
                gap_ratio = (gap_cfg / 100.0)
                buy_offset_val = current_price * off_ratio
                gap_val = current_price * gap_ratio
            else:
                buy_offset_val = offset_cfg
                gap_val = gap_cfg
            
            sell_offset_val = buy_offset_val
            buy_offset_val = round(buy_offset_val, digits)
            sell_offset_val = round(sell_offset_val, digits)
            gap_val = round(gap_val, digits)

            # Manual TP is taken exactly from UI setting, but used as a BASKET TP in process_tick
            # We enforce no hard SL/TP on the individual orders for the manual bot.
            min_tp_dist = 0.0
            min_sl_dist = 0.0

            side_cfg = str(getattr(self, "pending_order_side_mode", "BOTH_SIDES")).upper()
            place_buy, place_sell = True, True
            if (("BUY" in side_cfg and "ONLY" in side_cfg) or side_cfg == "BUY"):
                place_buy, place_sell = True, False
            elif (("SELL" in side_cfg and "ONLY" in side_cfg) or side_cfg == "SELL"):
                place_buy, place_sell = False, True

            directional_sell = place_sell and not place_buy
            directional_buy  = place_buy  and not place_sell
            ranging_mode     = place_buy  and place_sell

            dir_tp_dist = 0.0

            placed_count = 0
            base_start_offset = buy_offset_val

            cumulative_gap = 0.0
            expansion_factor = 1.0  # 1.0 ensures perfectly uniform gaps exactly matching the user's parameter

            for i in range(effective_levels):
                buy_size  = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)
                sell_size = self.calculate_level_size(self.order_size, self.order_size_multiplier, i)

                if directional_sell:
                    sell_stop_px = round(bid_ref - base_start_offset - cumulative_gap, digits)
                    try:
                        r = self.broker.place_order("SELL_STOP", sell_stop_px, sell_size, timestamp, tp=0.0, sl=0.0)
                        if r: placed_count += 1
                    except Exception as e: print(f"[{sym_name}] SELL_STOP L{i} error: {e}")

                elif directional_buy:
                    buy_stop_px = round(ask_ref + base_start_offset + cumulative_gap, digits)
                    try:
                        r = self.broker.place_order("BUY_STOP", buy_stop_px, buy_size, timestamp, tp=0.0, sl=0.0)
                        if r: placed_count += 1
                    except Exception as e: print(f"[{sym_name}] BUY_STOP L{i} error: {e}")

                else:
                    buy_px  = round(ask_ref + base_start_offset + cumulative_gap, digits)
                    try:
                        r = self.broker.place_order("BUY_STOP", buy_px, buy_size, timestamp, tp=0.0, sl=0.0)
                        if r: placed_count += 1
                    except Exception as e: print(f"[{sym_name}] BUY_STOP L{i} error: {e}")

                    sell_px = round(bid_ref - base_start_offset - cumulative_gap, digits)
                    try:
                        r = self.broker.place_order("SELL_STOP", sell_px, sell_size, timestamp, tp=0.0, sl=0.0)
                        if r: placed_count += 1
                    except Exception as e: print(f"[{sym_name}] SELL_STOP L{i} error: {e}")

                cumulative_gap += gap_val * (expansion_factor ** i)

            if hasattr(self.broker, "purge_duplicate_mt5_orders"):
                try: self.broker.purge_duplicate_mt5_orders()
                except: pass

            if placed_count > 0 or len(self.broker.pending_orders) > 0:
                self.deployed = True
                self.deploy_price = current_price
                self.last_deploy_time = timestamp
                print(f"[{sym_name}] ⚡ [MANUAL GRID DEPLOYED] {placed_count} Traps @ ${current_price:,.2f} | Gap: ${gap_val:.2f} | Offset: ${buy_offset_val:.2f} | Lot: {self.order_size}")
            else:
                self.deployed = False
                self.last_deploy_time = timestamp
                
        except Exception as e:
            self.deployed = False
            print(f"[{sym_name}] Manual Deployment exception: {e}")
        finally:
            self._is_deploying = False

    def cleanup_stale_grid_orders(self, current_price: float) -> int:
        if self.deployed or len(self.broker.pending_orders) <= (self.grid_levels * 2):
            return 0
        if not self.broker.pending_orders:
            return 0

        center_price = self.deploy_price if self.deploy_price > 0 else current_price

        if getattr(self, "deploy_grid_gap", None) and getattr(self, "deploy_trap_offset", None):
            gap_val = self.deploy_grid_gap
            buy_offset_val = self.deploy_trap_offset
            sell_offset_val = buy_offset_val
        else:
            if getattr(self, "is_percent", True):
                off_ratio = (self.trap_offset / 100.0) if self.trap_offset >= 0.50 else (self.trap_offset if self.trap_offset < 0.01 else self.trap_offset / 100.0)
                gap_ratio = (self.grid_gap / 100.0) if self.grid_gap >= 0.50 else (self.grid_gap if self.grid_gap < 0.01 else self.grid_gap / 100.0)
                buy_offset_val = center_price * off_ratio
                gap_val = center_price * gap_ratio
            else:
                buy_offset_val = self.trap_offset
                gap_val = self.grid_gap
            sell_offset_val = buy_offset_val

        tolerance = max(gap_val * 1.5, center_price * 0.005)

        valid_buy_levels = [center_price + buy_offset_val + (i * gap_val) for i in range(self.grid_levels)]
        valid_sell_levels = [center_price - sell_offset_val - (i * gap_val) for i in range(self.grid_levels)]

        cancelled_ids = []

        for order_id, order in list(self.broker.pending_orders.items()):
            if order_id in cancelled_ids:
                continue
            order_age = (time.time() - getattr(order, "timestamp", time.time())) if hasattr(order, "timestamp") else 999.0
            if self.deployed and order_age < 300.0:
                continue

            if order.type == "BUY_STOP":
                valid_levels = valid_buy_levels
            elif order.type == "SELL_STOP":
                valid_levels = valid_sell_levels
            else:
                continue

            is_valid = any(abs(order.trigger_price - lvl) < tolerance for lvl in valid_levels)
            if not is_valid:
                self.broker.cancel_order(order_id)
                cancelled_ids.append(order_id)

        from collections import defaultdict
        buy_groups = defaultdict(list)
        sell_groups = defaultdict(list)

        for order_id, order in list(self.broker.pending_orders.items()):
            if order_id in cancelled_ids:
                continue
            if order.type == "BUY_STOP":
                for lvl in valid_buy_levels:
                    if abs(order.trigger_price - lvl) < tolerance:
                        buy_groups[round(lvl, 8)].append((order_id, order))
                        break
            elif order.type == "SELL_STOP":
                for lvl in valid_sell_levels:
                    if abs(order.trigger_price - lvl) < tolerance:
                        sell_groups[round(lvl, 8)].append((order_id, order))
                        break

        def cancel_duplicates_in_group(group_dict):
            count = 0
            for lvl, orders in group_dict.items():
                if len(orders) > 1:
                    orders.sort(key=lambda x: abs(x[1].trigger_price - lvl))
                    for order_id, _ in orders[1:]:
                        self.broker.cancel_order(order_id)
                        cancelled_ids.append(order_id)
                        count += 1
            return count

        cancel_duplicates_in_group(buy_groups)
        cancel_duplicates_in_group(sell_groups)

        return len(cancelled_ids)

    def process_tick(self, previous_price: float, current_price: float, timestamp: float, bb_width: Optional[float] = None) -> Optional[dict]:
        # 1. Update Broker
        newly_filled_pos_ids = []
        if hasattr(self.broker, "process_tick"):
            new_positions = self.broker.process_tick(previous_price, current_price, timestamp)
            if new_positions:
                newly_filled_pos_ids = [pos.position_id for pos in new_positions if hasattr(pos, "position_id")]
        elif hasattr(self.broker, "update_pending_orders"):
            newly_filled_pos_ids = self.broker.update_pending_orders(current_price, timestamp)

        current_open = len(getattr(self.broker, "open_positions", {}))
        current_pending = len(getattr(self.broker, "pending_orders", {}))

        # 2. Check Basket PNL Take Profit
        if current_open > 0:
            total_pnl_raw = self.broker.get_floating_pnl(current_price)
            is_cent = getattr(self.broker, "is_cent_account", False)
            total_pnl = (total_pnl_raw / 100.0) if is_cent else total_pnl_raw
            target_usd = float(getattr(self, "target_profit", 15.0))
            if target_usd > 0 and total_pnl >= target_usd:
                print(f"[{self.symbol}] 🎯 [MANUAL TP HIT] Basket PNL ${total_pnl:.2f} (raw={total_pnl_raw:.2f}) >= Target ${target_usd:.2f}. Closing all & restarting.")
                try:
                    self.broker.close_all_positions(symbol=self.symbol)
                    self.broker.cancel_all_orders(symbol=self.symbol)
                except Exception as e:
                    import logging; logging.warning(f"Basket TP close error: {e}")
                
                if hasattr(self, "record_trade_outcome"):
                    self.record_trade_outcome(total_pnl, "MANUAL_BASKET_TP", 0)
                
                # Restart exact same grid!
                self._max_open_in_cycle = 0
                self.deploy_traps(current_price, timestamp, force=True)
                return None

        # 3. If positions closed manually (e.g. from UI) but traps remain, auto restart
        if getattr(self, "_max_open_in_cycle", 0) > 0 and current_open == 0 and current_pending > 0:
            print(f"[{self.symbol}] 🔄 [MANUAL RESTART] Cycle closed. Redeploying manual grid.")
            try: self.broker.cancel_all_orders(symbol=self.symbol)
            except: pass
            self._max_open_in_cycle = 0
            self.deploy_traps(current_price, timestamp, force=True)
            return None

        if current_open > getattr(self, "_max_open_in_cycle", 0):
            self._max_open_in_cycle = current_open

        return None
