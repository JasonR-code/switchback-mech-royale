"""Pre-hit laser warnings: for each rival laser hit on us, what could the bot have seen?

Observable signals only (obs.mechs with charging=true, their aim, laser_charge sounds are not
simulated by the labs). For every laser hit we record: rear or front, whether the charger
appeared in obs.mechs with charging=true before the hit, the warning lead time, the angle
between our aim and the charger at first warning, the turn needed to bring it inside the
front half-arc (90 deg minus 8 deg margin) and whether our combat focus was another rival.
Usage: python validation/laser_warning_probe.py <bot-dir> map|open <split> <cases> <rival-damage> p|n
"""
import collections
import json
import math
import sys
from pathlib import Path

bot, lab, split, n, scale, prov = Path(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5]), sys.argv[6] == 'p'
sys.path.insert(0, str(bot))
sys.path.insert(1, str(Path(__file__).resolve().parent))
from combat import Combat, wrap  # noqa: E402
from main import Pilot  # noqa: E402
if lab == 'map':
    import combat_map as L
    Sim = L.MapSnowball
else:
    import combat_snowball as L
    Sim = lambda *a, **k: L.Snowball(*a, fov=True, **k)
cfg = json.loads((bot/'defaults.json').read_text())
C = collections.Counter()
leads, turns = [], []
for seed in L.cases(split, n):
    pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir='none')))
    sim = Sim(Combat, cfg, seed, pilot, scale=scale, provoke=prov)
    warn = {}
    orig = pilot.act

    def act(obs, _o=orig):
        me = obs['self']
        for m in obs['mechs']:
            if m.get('charging'):
                b = math.atan2(m['pos'][1]-me['pos'][1], m['pos'][0]-me['pos'][0])
                aimed = abs(wrap(m['aim'][0] - (b + math.pi))) < .35
                if m['id'] not in warn:
                    warn[m['id']] = (obs['t'], abs(wrap(b - me['aim'][0])), aimed, pilot.combat.focus)
        for i in list(warn):
            if not any(m['id'] == i and m.get('charging') for m in obs['mechs']) and obs['t'] - warn[i][0] > 4:
                warn.pop(i)
        out = _o(obs)
        return out
    pilot.act = act
    hm = sim.hurt_me

    def hurt(r, amount, weapon, source, _o=hm):
        _o(r, amount, weapon, source)
        if weapon != 'laser':
            return
        e = sim.events[-1]
        C['hits'] += 1
        C['dmg'] += e['amount']
        C['rear hits'] += e['rear']
        C['rear dmg'] += e['amount'] if e['rear'] else 0
        w = warn.pop(r.id, None)
        if w:
            t0, angle, aimed, focus = w
            C['warned'] += 1
            C['warned & aimed-at-us'] += aimed
            lead = sim.t - t0
            leads.append(lead)
            need = max(0., angle - math.radians(82))
            turns.append(need)
            if e['rear']:
                C['rear & warned'] += 1
                C['rear & warned & turn fits in lead'] += need/4. + .1 < lead
                C['rear & warned & focus elsewhere'] += focus is not None and focus != r.id
    sim.hurt_me = hurt
    sim.run()
h = max(1, C['hits'])
print(f"laser hits {C['hits']} dmg {C['dmg']:.0f}  rear hits {C['rear hits']} ({C['rear hits']/h:.0%}), rear dmg {C['rear dmg']:.0f}"
      f" = extra {C['rear dmg']/3:.0f} over front")
for k in ('warned', 'warned & aimed-at-us', 'rear & warned', 'rear & warned & turn fits in lead', 'rear & warned & focus elsewhere'):
    print(f'  {k:36s} {C[k]:5d}  {C[k]/h:6.1%} of hits')
if leads:
    leads.sort()
    print(f'  warning lead s: median {leads[len(leads)//2]:.2f}  p25 {leads[len(leads)//4]:.2f}')
