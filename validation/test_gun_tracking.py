"""Rival-specific gun prediction and independence of hitscan weapon aim."""
from math import cos, hypot, sin
import unittest

from test_combat import CFG, Combat, Flat, observation
from gun_tracking import GunTrack


class GunTrackingTests(unittest.TestCase):
    def test_steady_velocity_and_observation_gap(self):
        track = GunTrack()
        for i in range(30):
            velocity = (0., 10., 0.)
            self.assertEqual(track.step(i/10, (80, i, 0), velocity, velocity, .4, (1, 0)), velocity)
        self.assertEqual(track.step(5., (10., 15., 0.), (5., 0., 3.), (4., 0., 3.), .4, (1, 0)),
                         (4., 0., 3.))
        self.assertEqual(len(track.history), 1)

    def test_turn_prediction_reduces_crossing_error(self):
        track = GunTrack()
        speed, rate, horizon = 12., 1.8, .5
        def feet(t):
            return 135.+speed*sin(rate*t)/rate, speed*(1-cos(rate*t))/rate, 0.
        for i in range(34):
            t=i*.1
            p=feet(t)
            v=(speed*cos(rate*t),speed*sin(rate*t),0.)
            baseline=(v[0]*.92,v[1]*.92,0.)
            pred=track.step(t,p,v,baseline,horizon,(1.,0.))
        target=feet(t+horizon)
        def error(forecast):
            return hypot(p[0]+horizon*forecast[0]-target[0],p[1]+horizon*forecast[1]-target[1])
        self.assertLess(error(pred), .75*error(baseline))

    def test_gun_and_laser_do_not_share_projectile_forecasts(self):
        bot=Combat(CFG)
        obs=observation('gun','laser',distance=130)
        foe=obs['mechs'][0]
        for i in range(32):
            t=i*.1
            foe['pos']=[130+7*sin(1.8*t),7*(1-cos(1.8*t)),0.]
            foe['vel']=[12.6*cos(1.8*t),12.6*sin(1.8*t),0.]
            obs['t']=t
            target=bot.contacts(obs,{},(0.,0.,7.))[0]
        self.assertGreater(hypot(target.gun_velocity[0]-target.velocity[0],
                                 target.gun_velocity[1]-target.velocity[1]),1.)
        obs['self']['weapons'] = obs['self']['weapons'][1:]
        laser_only=Combat(CFG)
        a=bot.act(obs,Flat(),{})
        laser_only.previous=bot.previous.copy()
        b=laser_only.act(obs,Flat(),{})
        self.assertEqual(a['aim'],b['aim'])
        self.assertEqual(a['fire'],b['fire'])
        self.assertFalse(laser_only.gun_tracks)
