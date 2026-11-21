"""Trace a fixed paired full-match campaign. Spectator metrics never enter observations."""
import argparse
import gzip
import json
import math
import sys
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--bot', type=Path, required=True)
p.add_argument('--harness', type=Path, required=True)
p.add_argument('--base', type=int, required=True)
p.add_argument('--cases', type=int, nargs='+', required=True)
p.add_argument('--routed', action='store_true')
p.add_argument('--trace', type=Path)
args = p.parse_args()
sys.path[:0] = [str(args.bot.resolve()), str((args.harness/'validation').resolve())]
from arena import Arena
from campaign import Campaign, Campus, ZoneRoutes

class Monitor(Campaign):
    def __init__(self, *params):
        super().__init__(*params)
        self.last_hit = {}
        self.second_at = None
        self.pressure_frames = self.diverted = self.unseen_frames = 0
        self.bearing_frames = 0
        self.exposed_waypoints = self.toward_extra = 0
        self.open_lanes = set()
        self.details = []
        self.impacts = []
        self.reported = set()
        self.pressure_hits = self.post_damage = self.post_crossfire = 0
        move = self.pilot.motion.act

        def measure(obs, arena, waypoint, intent):
            t, me = obs['t'], obs['self']
            if args.trace:
                self.reported = {e['id'] for e in obs['mechs']}
            for event in obs['events']:
                if event['type'] == 'damaged' and event.get('by') is not None:
                    self.last_hit[event['by']] = t
                if event['type'] == 'kill':
                    self.last_hit.pop(event['target'], None)
            ids = sorted(i for i, when in self.last_hit.items() if 0 <= t-when <= 3)
            if len(ids) >= 2:
                if self.second_at is None:
                    self.second_at = t
                self.pressure_frames += 1
                self.bearing_frames += bool(intent.get('incoming_guns'))
                self.diverted += bool(intent.get('lane_cover'))
                reported = {e['id'] for e in obs['mechs']}
                self.unseen_frames += bool(set(ids)-reported)
                if args.trace:
                    pos = me['pos']
                    d = math.dist(pos[:2], waypoint[:2])
                    f = min(1, 9 / max(.001, d))
                    nx, ny = (a+f*(b-a) for a,b in zip(pos, waypoint))
                    nz = arena.surface(nx,ny,pos[2]) + me['stats']['height']*.55
                    def open_from(eye):
                        return {a['id'] for a in self.actors[1:] if a['hp']>0 and
                                self.world.visible([*a['pos'][:2],a['pos'][2]+7],eye)}
                    here = open_from([*pos[:2],pos[2]+me['stats']['height']*.55])
                    there = open_from([nx,ny,nz])
                    self.toward_extra += bool(there - here)
                    self.exposed_waypoints += len(there.intersection(ids)) >= 2
                    self.details.append(dict(t=round(t,2), ids=ids, unseen=sorted(set(ids)-reported),
                        here=sorted(here), there=sorted(there), escape=intent['escape'],
                        urgent=intent['urgent'], goal=self.pilot.strategy.last_goal[2], waypoint=waypoint,
                        lane_cover=bool(intent.get('lane_cover')), focus=self.pilot.combat.focus,
                        hp=round(me['hp']), energy=round(me['energy'])))
            return move(obs,arena,waypoint,intent)
        self.pilot.motion.act = measure

    def move_squad(self, *args):
        lanes=super().move_squad(*args)
        self.open_lanes={i for i,open_ in lanes.items() if open_}
        if self.second_at is not None and self.time < self.second_at+12:
            self.post_crossfire += .05*(len(self.open_lanes)>=2)
        return lanes

    def damage_actor(self, source, target, amount, bearing, kind):
        hp=self.me['hp']
        super().damage_actor(source,target,amount,bearing,kind)
        if args.trace and target == 0 and hp > 0:
            vx,vy=self.me['vel'][:2]
            ident=self.actors[source]['id']
            self.impacts.append(dict(t=round(self.time,2), by=ident, weapon=kind, bearing=round(bearing,3),
                reported=ident in self.reported, lateral=round(abs(vx*math.sin(bearing)-vy*math.cos(bearing)),2),
                speed=round(math.hypot(vx,vy),2),damage=round(hp-self.me['hp'],1)))
        if target == 0 and self.second_at is not None and self.time < self.second_at+12:
            self.pressure_hits += 1
            self.post_damage += max(0,hp-self.me['hp'])

    def run(self):
        row=super().run()
        t=self.second_at
        # A win ends danger and earns the remainder of the restricted survival window.
        life=None if t is None else (12 if row['survived'] else min(12, max(0,self.time-t)))
        row.update(second_at=t, post12_alive=life, post12_damage=round(self.post_damage,2),
                   post12_crossfire=round(self.post_crossfire,2), active_frames=self.pressure_frames,
                   missing_frames=self.unseen_frames, cover_frames=self.diverted, bearing_frames=self.bearing_frames)
        if args.trace:
            row.update(waypoint_two=self.exposed_waypoints,waypoint_extra=self.toward_extra)
        return row

kit = args.harness/'mechfight-kit'
world = Campus(kit)
geometry = Arena(kit/'arena')
assert geometry.handle,geometry.error
world.visible = geometry.clear
if args.routed:
    world.routes=ZoneRoutes(world,geometry)
trace = gzip.open(args.trace,'wt') if args.trace else None
try:
    for i in args.cases:
        game=Monitor(world,kit,args.base+1381*i,i,'mixed',True)
        row=game.run()
        print(json.dumps(row),flush=True)
        if trace:
            print(json.dumps(dict(seed=row['seed'],decisions=game.details,impacts=game.impacts)),file=trace,flush=True)
finally:
    if trace:
        trace.close()
