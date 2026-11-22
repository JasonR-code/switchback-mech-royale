"""Selective cover on two intersecting lines of fire; scripted geometry for precise edges."""
import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from isolation import Isolation

class Corner:
    handle=True
    def clear(self,a,b):
        # The northern rival is screened once the player moves east of the corner.
        return not (a[1]>60 and b[0]>3)
    def walkable(self,*p): return True
    def can_move(self,a,b): return True
    def surface(self,x,y,z): return z

class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.policy=Isolation(); self.arena=Corner()
        self.me=dict(id=0,pos=[0,0,0],grounded=True,stats=dict(height=9))
        def rival(i,x,y,yaw):
            return dict(id=i,kind='mech',pos=[x,y,0],hp=900,aim=[yaw,0],vel=[0,0,0])
        self.a,self.b=rival(1,90,0,math.pi),rival(2,0,80,-math.pi/2)
        self.obs=dict(t=5.,self=self.me,mechs=[self.a,self.b],events=[],zone=dict(center=[0,0],radius=100,next_center=[0,0],next_radius=100))
        self.intent=dict(urgent=False,escape=True,goal=[0,0,0])
    def pick(self,focus=1):
        return self.policy.choose(self.obs,self.arena,self.intent,focus,{})
    def test_select_and_reuse_reachable_corner(self):
        p=self.pick()
        self.assertGreater(p[0],3)
        self.obs['t']+=.1
        self.assertEqual(self.pick(),p)
    def test_drop_lock_for_urgent_or_lost_rival(self):
        self.assertIsNotNone(self.pick())
        self.obs['mechs']=[self.a]
        self.assertIsNone(self.pick())
        self.obs['mechs'].append(self.b)
        self.intent['urgent']=True
        self.assertIsNone(self.pick())
    def test_preserve_finish_and_missing_hp(self):
        for hp in (100,None):
            if hp:self.a['hp']=hp
            else:self.a.pop('hp')
            self.assertIsNone(self.pick())
    def test_stay_on_existing_cover_route(self):
        self.intent['goal']=[5,0,0]
        self.assertIsNone(self.pick())
    def test_reject_blocked_or_outside(self):
        self.arena.can_move=lambda *_:False
        self.assertIsNone(self.pick())
        self.arena.can_move=lambda *_:True
        self.obs['t']+=1
        self.obs['zone'].update(radius=5,next_radius=5)
        self.assertIsNone(self.pick())
    def test_unengaged_bystander_and_reported_hit(self):
        self.b['aim']=[math.pi/2,0]
        self.assertIsNone(self.pick())
        self.obs['events']=[dict(type='damaged',by=2)]
        self.assertIsNotNone(self.pick())
