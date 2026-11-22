"""How glances interact with firing, and what follows a reveal (snowball lab, protocol vision).

Per decision with intent.glance set, combat is also run on a deep copy *without* the
glance (same state), giving the counterfactual trigger: gun shots and laser releases
the glance withheld. Also counts escapes in the 3 s after a glance ends with the
shooter reported, and whether the target we had then died within 5 s.
Usage: python validation/glance_probe.py <bot-dir> <split> <cases> <rival-damage> p|n
"""
import copy, json, sys, collections
from pathlib import Path
bot, split, n, scale, prov = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), sys.argv[5] == 'p'
sys.path.insert(0, str(bot)); sys.path.insert(1, str(Path(__file__).resolve().parent))
import combat_snowball as cb
from combat import Combat
from main import Pilot
cfg = json.loads((bot/'defaults.json').read_text())
C = collections.Counter()
for seed in cb.cases(split, n):
    pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir='none')))
    sim = cb.Snowball(Combat, cfg, seed, pilot, scale=scale, provoke=prov, fov=True)
    st, cm = pilot.strategy, pilot.combat
    state = dict(last_glance=None, reveal_t=None, reveal_focus=None)
    orig_act, orig_plan = cm.act, st.plan
    def act(obs, arena, intent, _o=orig_act, _c=cm):
        C['decisions'] += 1
        g = intent.get('glance')
        if g is None:
            return _o(obs, arena, intent)
        C['glance'] += 1
        shadow = copy.deepcopy(_c)
        cf = Combat.act(shadow, obs, arena, {k: v for k, v in intent.items() if k != 'glance'})
        real = _o(obs, arena, intent)
        if abs(real['aim'][0] - cf['aim'][0]) > 1e-6:
            C['glance_turned'] += 1
        for slot, w in enumerate((obs['self'].get('weapons') or [])[:2]):
            if not w:
                continue
            if w['kind'] == 'gun':
                if cf['fire'][slot] and not real['fire'][slot]:
                    C['gun_shot_withheld'] += 1
                if cf['fire'][slot]:
                    C['gun_shot_cf'] += 1
            if w['kind'] == 'laser' and w.get('charge', 0) > 0:
                if not cf['fire'][slot] and real['fire'][slot]:
                    C['laser_release_withheld'] += 1
                    if w.get('charge', 0) >= .74: C['full_laser_release_withheld'] += 1
                if not cf['fire'][slot]:
                    C['laser_release_cf'] += 1
        return real
    def plan(obs, arena, _o=orig_plan):
        out = _o(obs, arena)
        t = obs['t']
        if state['last_glance'] is not None and out.get('glance') is None:
            state['reveal_t'] = t
            state['reveal_focus'] = cm.focus
            C['glance_episodes'] += 1
        state['last_glance'] = out.get('glance')
        if state['reveal_t'] is not None and t - state['reveal_t'] <= 3:
            C['post_reveal_decisions'] += 1
            C['post_reveal_escape'] += bool(out['escape'])
        return out
    cm.act, st.plan = act, plan
    sim.run()
d = C['decisions']
for k in sorted(C):
    print(f'{k:28s} {C[k]:7d}  {C[k]/d:6.2%} of decisions')
