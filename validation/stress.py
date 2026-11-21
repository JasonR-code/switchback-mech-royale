"""Decision time on deliberately dense valid game observations using the real map."""
import copy
import gzip
import json
import math
import random
import resource
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'bot' if (root/'bot/main.py').exists() else root))
from main import Pilot


def run():
    kit = root/'mechfight-kit'
    with gzip.open(kit/'check/stream.jsonl.gz') as f:
        hello, base = json.loads(next(f)),json.loads(next(f))
    hello['map']['dir'] = str(kit/'arena')
    bot = Pilot(hello)
    assert bot.arena.handle, bot.arena.error
    rng = random.Random(627411)
    times = []
    for k in range(800):
        o = copy.deepcopy(base)
        x,y = rng.uniform(-380,420), rng.uniform(-230,270)
        z = bot.arena.ground(x,y)
        o['self'].update(pos=[x,y,z],cubes=k%11)
        o.update(t=.1*k,tick=2*k,alive=16)
        secondary = ['mortar','laser','lightning'][k%3]
        o['self']['weapons'][1] = dict(kind=secondary,stats=hello['config']['weapons'][secondary],cooldown=0,charge=.75 if secondary=='laser' else 0)
        def point():
            return [x+rng.uniform(-75,75), y+rng.uniform(-75,75), z]
        o['mechs'] = [dict(id=i, kind='mech', pos=point(),vel=[6,-2,0],aim=[.5,.1],hp=600,
                           weapons=['gun','laser'],charging=True) for i in range(16) if i!=hello['slot']]
        o['mechs'] += [dict(id=i+100,kind='npc',pos=point(),vel=[0,3,0],aim=[1,0],hp=240) for i in range(12)]
        o['projectiles'] = [dict(id=i,kind='gun' if i%3 else 'mortar',pos=point(),
                                 vel=[rng.uniform(-200,200),rng.uniform(-200,200),rng.uniform(-8,8)]) for i in range(60)]
        for field, offset in [('crates',1000), ('cubes',5000), ('pickups',8000)]:
            o[field]=[dict(id=offset+i,pos=point()) for i in range(24)]
        for item in o['pickups']:
            item['kind']='lightning'
        raw = json.dumps(o,separators=(',',':'))
        assert len(raw)<65536
        start=time.perf_counter_ns()
        action=bot.act(json.loads(raw))
        json.dumps(action,allow_nan=False)
        times.append((time.perf_counter_ns()-start)/1e6)
        assert action['tick']==2*k
    times.sort()
    print(f'{len(times)} dense decisions, p50 {times[400]:.2f}, p99 {times[792]:.2f}, max {times[-1]:.2f} ms, '
          f'{sum(t>50 for t in times)} >50 ms, process peak {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.1f} MiB')


if __name__=='__main__':
    run()
