"""Integration and resilience checks against the supplied mechfight/1 contract."""
import copy
import gzip
import importlib.util
import json
import math
import os
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT = ROOT/'bot' if (ROOT/'bot/main.py').exists() else ROOT
KIT = Path(os.environ.get('MECHFIGHT_KIT', ROOT/'mechfight-kit'))
sys.path.insert(0, str(BOT))
from main import Pilot


class PilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(KIT/'check/stream.jsonl.gz') as f:
            cls.hello, cls.frame = json.loads(next(f)), json.loads(next(f))
        cls.hello['map']['dir'] = str(KIT/'arena')
        spec = importlib.util.spec_from_file_location('official_checker', KIT/'check/check.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        cls.schema = checker.Schema(KIT/'mechfight.schema.json')
        cls.pilot = Pilot(cls.hello)

    def check_action(self, obs):
        action = self.pilot.act(obs)
        self.assertEqual(action['tick'],obs['tick'])
        self.assertEqual(self.schema.errors(action,'Action'), [])
        json.dumps(action, allow_nan=False)
        if 'move' in action:
            self.assertLessEqual(math.hypot(*action['move']), 1.000001)
        return action

    def test_official_map_loaded(self):
        self.assertTrue(self.pilot.arena.handle, self.pilot.arena.error)
        self.assertGreater(self.pilot.arena.bounds[2], 500)

    def test_two_guns_produce_outward_movement_actions(self):
        from test_strategy import enemy, observed
        hello = self.hello | {"seed":20,"map":{"dir":"/unmapped-flat-arena"}}
        for offset in (100,150):
            obs = observed()
            obs["mechs"] = [enemy(3,offset,20), enemy(4,offset,-20)]
            action = Pilot(hello).act(obs)
            self.assertEqual(self.schema.errors(action, "Action"), [])
            for mech in obs["mechs"]:
                toward = mech["pos"][:2]
                self.assertLess(sum(a*b for a,b in zip(action["move"], toward)), 0)

    def test_partial_observations(self):
        self.check_action({'tick': 4432})
        self.check_action({'tick': 4434,'self': {'pos':[None,0,0]}})
        self.check_action({'tick': 4436,'self': {'pos':[0,0,0], 'weapons':[None], 'stats':None}})
        self.check_action({'tick': 4438,'self': self.frame['self'], 'mechs':[{},None,{'id':7,'pos':[0,0,0],'kind':'mech'}],
                           'offer':{'choices':[]}, 'zone':{'center':[],'radius':None}, 'projectiles':[{},None],
                           'events':[None,{'type':'damaged','bearing':None}], 'beams':[{'path':[]}],
                           'drops':[{'id':20000,'pos':[0,0,0],'progress':None}]})

    def test_optional_fields_and_balance_changes(self):
        h = copy.deepcopy(self.hello)
        h['config']['mech']['walk_speed'] = 13.4
        h['config']['weapons']['gun']['speed'] = 308
        other = Pilot(h)
        self.assertEqual(other.config['weapons']['gun']['speed'],308)
        obs = {'tick':7320,'self':{'id':3,'pos':[0,0,0],'weapons':[{'kind':'gun','stats':{}}]},
               'future_field':102,'mechs':[{'kind':'mech','id':5,'pos':[10,10,0],'vel':[0,0,0],'aim':[0,0]}]}
        normalized = other._observation(obs)
        self.assertEqual(normalized['self']['stats']['walk_speed'],13.4)
        self.assertEqual(normalized['self']['weapons'][0]['stats']['speed'],308)
        self.assertEqual(self.schema.errors(other.act(obs),'Action'),[])

    def test_missing_map_and_changing_slots(self):
        h = self.hello | {'map': {'dir': '/no-such-campus-map'}}
        pilot = Pilot(h)
        self.assertFalse(pilot.arena.handle)
        obs = copy.deepcopy(self.frame)
        for i,w in enumerate([[], [None,{'kind':'laser'}], [{'kind':'mortar'},None],
                              [None,None], [{'kind':'unknown'}]]):
            obs['tick'] += 2
            obs['self']['weapons'] = w
            self.assertEqual(self.schema.errors(pilot.act(obs),'Action'),[])

    def test_random_optional_shapes(self):
        rng = random.Random(10001)
        for t in range(180):
            o = copy.deepcopy(self.frame)
            o['tick'],o['t'] = t*2,t*.1
            o['mechs']=[{'id':1,'kind':'mech','aim':[1,0],'vel':[0,0,0],'pos':[0,0,5],
                         'charging':False,'hp':600,'cubes':0,'weapons':['mortar']}]
            for key in ('vel','aim','hp','cubes','charging','weapons'):
                if rng.random() < .45:
                    del o['mechs'][0][key]
            for key in list(o['self']):
                if key!='pos' and rng.random()<.13:
                    del o['self'][key]
            o['offer']={'choices':[{'id':'nanites'}, {'id':'armor'}, {'id':'a_new_upgrade'}]}
            self.check_action(o)


if __name__ == '__main__':
    unittest.main()
