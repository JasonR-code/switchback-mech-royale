"""Count focus switches and abandoned low-HP rivals in the full-pilot squad lab."""
import json, sys
from pathlib import Path
bot = Path(sys.argv[1]); sys.path.insert(0, str(bot)); sys.path.insert(1, str(Path(sys.argv[2])))
import combat_squad as cs
from combat import Combat
from main import Pilot
cfg = json.loads((bot/'defaults.json').read_text())
sw = dec = abandon = low_seen = 0
for seed, own in cs.cases('holdout', 160):
    pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir='none')))
    sq = cs.Squad(Combat, cfg, seed, own, pilot=pilot)
    last = None; tick = 0
    while sq.t < 20 and any(r.alive for r in sq.rivals) and sq.hp_taken < 1400:
        obs = sq.observation(tick); a = pilot.act(obs)
        f = pilot.combat.focus
        low = {m['id'] for m in obs['mechs'] if m['hp'] <= 250}
        if low: low_seen += 1
        if low and f not in low and any(m['id'] in low and ((m['pos'][0]-obs['self']['pos'][0])**2+(m['pos'][1]-obs['self']['pos'][1])**2)**.5 < 200 for m in obs['mechs']): abandon += 1
        if last is not None and f is not None and f != last: sw += 1
        if f is not None: last = f
        dec += 1
        mv = a.get('move') or (0, 0); sq.move, sq.boost = (float(mv[0]), float(mv[1])), bool(a.get('boost'))
        sq.events = []; sq.cmd = list(a['aim']); sq.tick(a, True); sq.tick(a, False); tick += 2
print(f"decisions {dec} focus switches {sw} ({100*sw/max(1,dec):.1f}%/decision); decisions with a rival <=250hp in view {low_seen}, of which aiming elsewhere {abandon}")
