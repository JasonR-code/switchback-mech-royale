"""Paired comparison of two combat_snowball --fov result files (adds unseen-shooter and rear damage).
Usage: python validation/unseen_compare.py base.json cand.json"""
import json,sys,subprocess
from combat_compare import bootstrap
import statistics as st
b,c=(json.load(open(p)) for p in sys.argv[1:3])
f={'kills':lambda r:r['kills'],'alive':lambda r:r['death'] if r['death'] is not None else 120.,'death<60':lambda r:float(r['death_60']),
   'taken':lambda r:r['taken'],'hidden_taken':lambda r:r['hidden_taken'],'hidden_share':lambda r:r['hidden_taken']/max(1,r['taken']),'rear':lambda r:r['rear'],
   'dealt':lambda r:r['dealt'],'cubes':lambda r:r['cubes'],'first_kill':lambda r:r['first_kill'] if r['first_kill'] is not None else 121.}
for k,g in f.items():
    d=[g(y)-g(x) for x,y in zip(b,c)]; lo,hi=bootstrap(d)
    print(f'  {k:13s} base {st.fmean(map(g,b)):8.2f} cand {st.fmean(map(g,c)):8.2f} diff {st.fmean(d):+8.2f} [{lo:+.2f}, {hi:+.2f}]')
