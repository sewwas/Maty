import re

with open('c:/Users/User/Desktop/Maty/app.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Modify the Auto Desk to only use st.session_state.markets
code = code.replace(
    'all_markets_combined = list(st.session_state.markets.items()) + list(st.session_state.manual_markets.items())',
    'all_markets_combined = list(st.session_state.markets.items())'
)

# 2. Add the Manual Desk History table at the end of the manual tab
manual_hist_code = """
            import datetime
            st.markdown("#### 📜 Manual Cycle History")
            man_raw_history = []
            for m_sym_code, m_m_data in list(st.session_state.manual_markets.items()):
                m_bot = m_m_data["bot"]
                m_brk = m_m_data["broker"]
                if hasattr(m_brk, "sync_history_from_mt5"):
                    try: m_brk.sync_history_from_mt5(days=180)
                    except: pass
                if hasattr(m_bot, "sync_cycle_history_from_trades"):
                    try: m_bot.sync_cycle_history_from_trades()
                    except: pass
                
                m_cycles_list = list(getattr(m_bot, "cycle_history", []) or [])
                if hasattr(m_brk, "closed_trades") and m_brk.closed_trades:
                    existing_records = {(round(float(c.get("exit_time", c.get("timestamp", 0))), 1), round(float(c.get("pnl", c.get("total_pnl", 0))), 2)) for c in m_cycles_list}
                    for idx_tr, tr in enumerate(m_brk.closed_trades):
                        pnl_tr = float(tr.get("pnl", 0.0))
                        ts_tr  = float(tr.get("exit_time", time.time()))
                        st_tr  = float(tr.get("entry_time", ts_tr - 15.0))
                        ts_rnd = round(ts_tr, 1)
                        pnl_rnd = round(pnl_tr, 2)
                        
                        if (ts_rnd, pnl_rnd) in existing_records: continue
                        existing_records.add((ts_rnd, pnl_rnd))
                        dep_px = float(tr.get("deploy_price", tr.get("entry_price", tr.get("open_price", 0.0))))
                        ex_px  = float(tr.get("exit_price",  tr.get("close_price",  tr.get("price", 0.0))))
                        fl_cnt = int(tr.get("fills_count",   tr.get("trades_count",  tr.get("size", 1))))
                        m_cycles_list.append({
                            "cycle_id":    len(m_cycles_list) + 1,
                            "symbol":      tr.get("symbol", m_sym_code),
                            "pnl":         pnl_tr,
                            "total_pnl":   pnl_tr,
                            "deploy_price": dep_px,
                            "entry_price":  dep_px,
                            "exit_price":   ex_px,
                            "fills_count":  max(1, fl_cnt),
                            "trades_count": max(1, fl_cnt),
                            "exit_reason":  tr.get("exit_reason", "TARGET_PROFIT" if pnl_tr > 0 else "STOP_LOSS"),
                            "duration":     max(1, int(ts_tr - st_tr)),
                            "start_time":   st_tr,
                            "timestamp":    ts_tr,
                            "exit_time":    ts_tr,
                            "is_win":       pnl_tr > 0.0
                        })

                seen_keys = set()
                for idx, item in enumerate(m_cycles_list):
                    rec = dict(item)
                    rec["symbol"] = rec.get("symbol", m_sym_code)
                    pnl_val = float(rec.get("pnl", rec.get("total_pnl", 0.0)))
                    ts_val = float(rec.get("exit_time", rec.get("timestamp", rec.get("entry_time", 0.0))))
                    c_id = rec.get("cycle_id", idx + 1)
                    rec["pnl"] = pnl_val
                    rec["total_pnl"] = pnl_val
                    rec["timestamp"] = ts_val
                    rec["exit_time"] = ts_val
                    key = (rec["symbol"], c_id, round(ts_val, 1), round(pnl_val, 4))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        man_raw_history.append(rec)

            man_raw_history.sort(key=lambda x: x.get("exit_time", x.get("timestamp", 0.0)), reverse=True)
            
            table_rows_man = ""
            for c in man_raw_history[:30]:
                c_pnl = float(c.get('pnl', c.get('total_pnl', 0.0)))
                pnl_cls = "pnl-green" if c_pnl >= 0 else "pnl-red"
                sym_badge = c.get('symbol', 'UNK')
                dur_fmt = f"{c.get('duration', 1)}s" if c.get('duration', 1) < 60 else f"{int(c.get('duration', 1)//60)}m {int(c.get('duration', 1)%60)}s"
                try:
                    dt = datetime.datetime.fromtimestamp(c.get('exit_time', c.get('timestamp', time.time())))
                    t_exit = dt.strftime('%H:%M:%S')
                except:
                    t_exit = "-"
                table_rows_man += (
                    f"<tr>"
                    f"<td>#{c.get('cycle_id', '?')}</td>"
                    f"<td><strong>{sym_badge}</strong></td>"
                    f"<td>${float(c.get('deploy_price', c.get('entry_price', 0))):,.3f}</td>"
                    f"<td>${float(c.get('exit_price', 0)):,.3f}</td>"
                    f"<td>{c.get('fills_count', c.get('trades_count', 1))}</td>"
                    f"<td><span style='font-family:JetBrains Mono,monospace;color:#38bdf8'>⏱️ {dur_fmt}</span></td>"
                    f"<td><span style='background:#27272a;padding:2px 6px;border-radius:4px;font-size:0.72rem'>{c.get('exit_reason', 'TP')}</span></td>"
                    f"<td>{t_exit}</td>"
                    f"<td class='{pnl_cls}'><strong>${c_pnl:+,.2f}</strong></td>"
                    f"</tr>"
                )
            
            if table_rows_man:
                st.markdown(f'''
                <table class="fast-table" style="font-size:0.78rem">
                    <thead><tr><th>ID</th><th>Symbol</th><th>Entry</th><th>Exit</th><th>Fills</th><th>Duration</th><th>Reason</th><th>Time</th><th>PnL</th></tr></thead>
                    <tbody>{table_rows_man}</tbody>
                </table>
                ''', unsafe_allow_html=True)
            else:
                st.info("No manual trades closed yet.")
"""

target_string = '''                    <tbody>{trap_rows}</tbody>
                  </table>
                </div>
                ''', unsafe_allow_html=True)'''

code = code.replace(target_string, target_string + '\n' + manual_hist_code)

with open('c:/Users/User/Desktop/Maty/app.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('Done!')
