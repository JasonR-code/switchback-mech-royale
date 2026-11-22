import json, sys, collections
from pathlib import Path
bot = Path(sys.argv[1]); sys.path.insert(0, str(bot)); sys.path.insert(1, '.')
import combat_snowball as cb
from combat import Combat
from main import Pilot
cfg = json.loads((bot/'defaults.json').read_text())
cats = collections.Counter(); flags = collections.Counter(); n = 0
for seed in cb.cases('dev', 40):
    pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir='none')))
    sim = cb.Snowball(Combat, cfg, seed, pilot, scale=.3)
    orig = pilot.strategy.plan
    def plan(obs, arena, _o=orig, _s=pilot.strategy):
        out = _o(obs, arena)
        g = _s.last_goal; cats[g[2] if g else None] += 1
        lf = _s.last_flags or ()
        if len(lf) > 5:
            flags['prey'] += lf[5] is not None and lf[5] is not False
            flags['finishing'] += lf[6] is not None
            flags['spoils'] += bool(lf[7])
        flags['escape'] += out['escape']; flags['visible'] += any(m['kind']=='mech' for m in obs['mechs'])
        return out
    pilot.strategy.plan = plan
    sim.run()
print('goal categories', dict(cats)); print('flags', dict(flags))
