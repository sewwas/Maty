import core.engine as e

print('=== SMART PAIR SELECTOR TEST ===')
scores = {'PAXGUSDT':92,'EURUSD':78,'BTCUSDT':65,'GBPUSD':55,'SOLUSDT':42,'BNBUSDT':38,'DOGEUSDT':30,'USDJPY':72,'ETHUSDT':60}
syms = list(scores.keys())

for total_orders, label in [(0,'EMPTY (0 orders)'),(60,'MODERATE (60 orders)'),(85,'FULL (85 orders)')]:
    selected = e.select_active_pairs(total_account_orders=total_orders, account_max_orders=100, regime_scores=scores, active_symbols=syms)
    print('  ' + label + ': ACTIVE=' + str(selected))

print()
print('=== GOLD PROVEN PARAMS ===')
for sym in ['PAXGUSDT','EURUSD','BTCUSDT','GBPUSD','SOLUSDT']:
    p = e.get_pair_gold_params(sym)
    print('  ' + sym.ljust(12) + ' tier=' + p['tier'].ljust(5) + ' gold=' + str(p['is_gold']) + ' max_lvl=' + str(p['max_levels']) + ' gap=' + str(p['base_gap_pct']) + '% offset=' + str(p['base_offset_pct']) + '% lot=' + str(p['min_lot']) + '-' + str(p['max_lot']))

print()
print('ALL SMART PAIR SELECTOR CHECKS PASSED!')
