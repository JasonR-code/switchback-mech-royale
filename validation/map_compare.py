"""Paired comparison of two combat_map.py result files.
Usage: python validation/map_compare.py base.json cand.json"""
import json
import statistics as st
import sys

from combat_compare import bootstrap

b, c = (json.load(open(p)) for p in sys.argv[1:3])
assert [r['seed'] for r in b] == [r['seed'] for r in c], 'different case lists'
life = lambda r: r['death'] if r['death'] is not None else 120.
f = {'kills (=outlasted)': lambda r: r['kills'], 'alive s': life, 'death<60': lambda r: float(r['death_60']),
     'died': lambda r: float(r['death'] is not None), 'taken': lambda r: r['taken'], 'rear': lambda r: r['rear'],
     'unseen taken': lambda r: r['hidden_taken'], 'dealt': lambda r: r['dealt'],
     'exposed s/min': lambda r: 60*r['exposed_s']/life(r), 'crossfire s/min': lambda r: 60*r['crossfire_s']/life(r),
     'escape s/min': lambda r: 60*r['escape_s']/life(r), 'escape taken': lambda r: r['escape_taken'],
     'cover s/min': lambda r: 60*r['cover_s']/life(r), 'first kill': lambda r: r['first_kill'] if r['first_kill'] is not None else 121.}
print(f"cases {len(b)}  deaths base {sum(r['death'] is not None for r in b)} cand {sum(r['death'] is not None for r in c)}")
for k, g in f.items():
    d = [g(y)-g(x) for x, y in zip(b, c)]
    lo, hi = bootstrap(d)
    print(f'  {k:18s} base {st.fmean(map(g, b)):8.2f} cand {st.fmean(map(g, c)):8.2f} diff {st.fmean(d):+8.2f} [{lo:+.2f}, {hi:+.2f}]')
