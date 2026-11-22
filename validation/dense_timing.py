"""Windows-safe copy of validation/stress.py: same dense scenario, no resource module, no-map arena."""
import copy, gzip, json, random, sys, time
from pathlib import Path
bot_dir, kit = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(bot_dir))
from main import Pilot
with gzip.open(kit/'check/stream.jsonl.gz') as f:
    hello, base = json.loads(next(f)), json.loads(next(f))
bot = Pilot(hello); rng = random.Random(627411); times = []
for k in range(800):
    o = copy.deepcopy(base); x, y, z = rng.uniform(-380,420), rng.uniform(-230,270), 0.
    o['self'].update(pos=[x,y,z], cubes=k%11); o.update(t=.1*k, tick=2*k, alive=16)
    s = ['mortar','laser','lightning'][k%3]
    o['self']['weapons'][1] = dict(kind=s, stats=hello['config']['weapons'][s], cooldown=0, charge=.75 if s=='laser' else 0)
    pt = lambda: [x+rng.uniform(-75,75), y+rng.uniform(-75,75), z]
    o['mechs'] = [dict(id=i, kind='mech', pos=pt(), vel=[6,-2,0], aim=[.5,.1], hp=600, weapons=['gun','laser'], charging=True) for i in range(16) if i != hello['slot']]
    o['mechs'] += [dict(id=i+100, kind='npc', pos=pt(), vel=[0,3,0], aim=[1,0], hp=240) for i in range(12)]
    o['projectiles'] = [dict(id=i, kind='gun' if i%3 else 'mortar', pos=pt(), vel=[rng.uniform(-200,200), rng.uniform(-200,200), rng.uniform(-8,8)]) for i in range(60)]
    for field, off in [('crates',1000), ('cubes',5000), ('pickups',8000)]:
        o[field] = [dict(id=off+i, pos=pt()) for i in range(24)]
    for item in o['pickups']: item['kind'] = 'lightning'
    raw = json.dumps(o, separators=(',',':')); t0 = time.perf_counter_ns()
    a = bot.act(json.loads(raw)); json.dumps(a, allow_nan=False); times.append((time.perf_counter_ns()-t0)/1e6)
    assert a['tick'] == 2*k
times.sort(); print(f"{bot_dir.name}: p50 {times[400]:.2f} p99 {times[792]:.2f} max {times[-1]:.2f} ms, >50ms: {sum(t>50 for t in times)}")
