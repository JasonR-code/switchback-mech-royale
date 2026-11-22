"""Repeated unseen attacks in the snowball lab (protocol vision): what follows them.

An episode starts when a rival we are not shown hits us a second time within 3 s
(or for >= 150 damage). Measured from the simulator side, so any bot is scored alike:
damage taken (all sources) and from that shooter in the next 4 s, kills by us and
our death within 4 s, and whether the shooter got reported to us within 1.5 s.
Usage: python validation/unseen_episode_probe.py <bot-dir> <split> <cases> <rival-damage> p|n [out.json]
"""
import json, sys, statistics as st
from pathlib import Path
bot, split, n, scale, prov = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), sys.argv[5] == 'p'
sys.path.insert(0, str(bot)); sys.path.insert(1, str(Path(__file__).resolve().parent))
import combat_snowball as cb
from combat import Combat
from main import Pilot
cfg = json.loads((bot/'defaults.json').read_text())
eps, cases_with = [], 0
for seed in cb.cases(split, n):
    pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir='none')))
    sim = cb.Snowball(Combat, cfg, seed, pilot, scale=scale, provoke=prov, fov=True)
    log, open_eps, done = [], [], []
    hm, ot = sim.hurt_me, sim.tick
    def hurt(r, amount, weapon, source, _o=hm):
        before = len(sim.hidden_events)
        _o(r, amount, weapon, source)
        dealt = sim.events[-1]['amount'] if sim.events and sim.events[-1].get('type') == 'damaged' else amount
        log.append((sim.t, r.id, dealt, len(sim.hidden_events) > before))
        if len(sim.hidden_events) > before and not any(e['by'] == r.id for e in open_eps):
            recent = [x for x in log if x[1] == r.id and x[3] and sim.t - x[0] <= 3]
            if len(recent) >= 2 or sum(x[2] for x in recent) >= 150:
                open_eps.append(dict(t=sim.t, by=r.id, kills0=sim.stats['kills'], seen=None))
    def tick(a, f, _o=ot):
        _o(a, f)
        for e in list(open_eps):
            if e['seen'] is None and sim.seen_t.get(e['by'], -1) >= e['t']:
                e['seen'] = sim.t - e['t']
            if sim.t - e['t'] >= 4 or sim.hp <= 0:
                w = [x for x in log if e['t'] < x[0] <= e['t'] + 4]
                done.append(dict(taken=sum(x[2] for x in w), from_shooter=sum(x[2] for x in w if x[1] == e['by']),
                                 kill=sim.stats['kills'] > e['kills0'], died=sim.hp <= 0,
                                 revealed=e['seen'] is not None and e['seen'] <= 1.5, t=e['t']))
                open_eps.remove(e)
    sim.hurt_me, sim.tick = hurt, tick
    sim.run()
    cases_with += bool(done); eps += done
m = lambda k: st.fmean(float(e[k]) for e in eps) if eps else 0
print(f'cases {n} with-episode {cases_with} episodes {len(eps)} ({len(eps)/n:.2f}/case) '
      f'taken4s {m("taken"):.0f} from-shooter4s {m("from_shooter"):.0f} kill4s {m("kill"):.2f} died4s {m("died"):.2f} revealed1.5s {m("revealed"):.2f}')
if len(sys.argv) > 6:
    json.dump(eps, open(sys.argv[6], 'w'))
