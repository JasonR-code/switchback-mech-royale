"""Run the existing dense benchmark with repeated protocol-valid incoming hits."""
import argparse
import importlib.util
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--bot', type=Path, required=True)
args = p.parse_args()
spec = importlib.util.spec_from_file_location('dense', args.bot.resolve()/'validation/stress.py')
dense = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dense)

class PressedPilot(dense.Pilot):
    cover_calls = bearing_ticks = 0

    def __init__(self, hello):
        super().__init__(hello)
        move = self.motion.act
        def count(obs,arena,waypoint,intent):
            PressedPilot.bearing_ticks += bool(intent.get('incoming_guns'))
            return move(obs,arena,waypoint,intent)
        self.motion.act = count
        if hasattr(self,'lane_cover'):
            find = self.lane_cover._find
            def measured(*a):
                PressedPilot.cover_calls += 1
                return find(*a)
            self.lane_cover._find = measured

    def act(self, frame):
        me = frame['self']
        ids = [e['id'] for e in frame['mechs'] if e['kind']=='mech' and e['id']!=me['id']]
        frame['mechs'] = [e for e in frame['mechs'] if e['id']!=ids[0]]
        frame['events'] = [dict(type='damaged',weapon='gun',amount=45,by=i,bearing=yaw)
                           for i,yaw in zip(ids[:4],(-.9,.8,1.6,-2.4))]
        me['grounded'],me['in_zone'] = True,True
        frame['zone'] = dict(center=[0,0],radius=560,next_center=[0,0],next_radius=560,
                             shrink_start=180,shrink_end=240,dps=20)
        return super().act(frame)

dense.Pilot = PressedPilot
dense.run()
print('cover scans', PressedPilot.cover_calls, 'bearing decisions', PressedPilot.bearing_ticks)
