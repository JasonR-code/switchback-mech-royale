"""Exercise the frozen cover policies against one wall and an open arena."""
import argparse
import math
from pathlib import Path
import sys

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--bot', type=Path, required=True)
args=p.parse_args()
sys.path[:0]=[str(args.bot.resolve()),str(args.bot.resolve()/'validation')]
from lane_cover import LaneCover
from test_strategy import WithWall, Plane, observed, enemy

class Wall(WithWall):
    climb_height=None
    def can_move(self,a,b):
        return all(self.walkable(a[0]+(b[0]-a[0])*i/30,a[1]+(b[1]-a[1])*i/30,0) for i in range(31))
class Open(Plane):
    climb_height=None
    def can_move(self,a,b):
        return True

obs=observed()
obs['self']['pos']=[-8.,0.,0.]
obs['mechs']=[enemy(3,40,0),enemy(4,60,-2)]
obs['events']=[dict(type='damaged',by=3,weapon='gun',bearing=0.)]
plan=LaneCover()
point=(-30.,0.)
intent={'urgent':False}
assert plan.waypoint(obs,Wall(),intent,point) is None
obs['t']+=.1
obs['events']=[dict(type='damaged',by=4,weapon='gun',bearing=0.)]
wall=Wall()
destination=plan.waypoint(obs,wall,intent,point)
assert destination and wall.can_move(obs['self']['pos'],destination)
assert any(not wall.clear((*e['pos'][:2],7),(*destination[:2],5)) for e in obs['mechs'])
assert plan.waypoint(obs,wall,{'urgent':True},point) is None
obs['events']=[dict(type='damaged',by=i,weapon='gun',bearing=0.) for i in (3,4)]
assert LaneCover().waypoint(obs,Open(),intent,point) is None
obs['mechs']=obs['mechs'][:1]
assert LaneCover().waypoint(obs,wall,intent,point)
obs['events']=[]
obs['t']+=4
assert plan.waypoint(obs,wall,intent,point) is None
print('PASS: staggered hits, traversable cover, urgent ring, open ground, missing shooter and expiry')
