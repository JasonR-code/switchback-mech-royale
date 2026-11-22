"""Why escape/recover is set in the snowball lab. Usage: python validation/snowball_escape_probe.py <bot-dir> <split> <rival-damage> p|n"""
import json, sys, collections
from math import cos, atan2
from pathlib import Path
bot = Path(sys.argv[1]); split = sys.argv[2]; scale = float(sys.argv[3]); provoke = sys.argv[4] == 'p'
sys.path.insert(0, str(bot)); sys.path.insert(1, str(Path(__file__).resolve().parent))
import combat_snowball as cb
from combat import Combat
from main import Pilot
import strategy as S
cfg = json.loads((bot/'defaults.json').read_text())
C = collections.Counter(); n = 0
for seed in cb.cases(split, 60):
    pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir='none')))
    sim = cb.Snowball(Combat, cfg, seed, pilot, scale=scale, provoke=provoke)
    st = pilot.strategy; orig = st.plan
    def plan(obs, arena, _o=orig, _s=st):
        out = _o(obs, arena)
        me = obs['self']; p = me['pos']; t = obs['t']; hp = me['hp']/me['max_hp']
        contacts, pressure = _s._perceive(obs, arena)
        vis = [c for c in contacts if c[3]]
        thr = [c for c in vis if _s._engaging(c, p, t)]
        C['n'] += 1
        C['vis%d' % min(len(vis), 3)] += 1
        C['thr%d' % min(len(thr), 3)] += 1
        if out['escape']:
            C['escape'] += 1
            r1 = pressure > .82 and (len(thr) > 1 or hp < .65)
            r2 = hp < .5 and pressure > .26
            r3 = len(thr) > 1 and hp < .7 and pressure > .55
            r4 = sum(c[0] > .26 for c in thr) >= 2
            key = 'esc:' + ''.join(k for k, v in (('1', r1), ('2', r2), ('3', r3), ('4', r4)) if v)
            C[key] += 1
            C['esc_thr%d' % min(len(thr), 3)] += 1
            if not thr: C['esc_no_engager_hp%.1f' % (int(hp*10)/10)] += 1
        if out['recover']: C['recover'] += 1
        if _s.last_goal: C['goal:' + _s.last_goal[2]] += 1
        return out
    st.plan = plan
    sim.run()
n = C.pop('n')
for k in sorted(C): print(f'{k:28s} {C[k]:6d} {C[k]/n:6.1%}')
print('decisions', n)
