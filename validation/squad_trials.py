"""Paired synthetic pursuit using the campus map, moving circles, guns and lightning.
Run once per policy with the same split/count. Uses official public map/config and
a hand-written squad, not the official game or house AI. Never computes placement.
"""
import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

from arena_trials import DT, Campus, Trial, clamp, delta, integrated
from skirmish import Skirmish, cylinder_entry


def elevated(actor, height):
    x, y, z = actor["pos"]
    return (x, y, z + height)


class Squad(Skirmish):
    def __init__(self, world, kit, seed, case, approach="mixed"):
        super().__init__(world, kit, integrated, seed)
        if not self.pilot.arena.handle:
            raise RuntimeError(f"native campus geometry unavailable: {self.pilot.arena.error}")
        self.family = "squad"
        self.limit = 28.0
        rng = random.Random(seed + 98411)
        self.enemy_count = 2 + case % 2
        self.start_time = (50., 280., 297.)[case % 3]
        self.mode = case % 3
        self.case = case
        self.initial_targets = []
        self.actors = [self.me]
        self.guns = [self.me["weapons"][0]]
        self.arcs = [None]
        self.leads = [0.]
        self.lanes = [0.]
        self.spray = [random.Random(seed + 3)]
        self.known = None
        self.seen_at = -1e5
        self.visible_at = [-1e5] * (self.enemy_count + 1)
        self.bearing_noise = random.Random(seed + 12011)
        self.sound_events = []
        self.beam_events = []
        self.last_combat = [-1e5] * (self.enemy_count + 1)
        self.last_spend = [-1e5] * (self.enemy_count + 1)
        self.zone_taken = [0.] * (self.enemy_count + 1)
        self.shots = [0] * (self.enemy_count + 1)
        self.hits = [0] * (self.enemy_count + 1)
        self.damage = [0.] * (self.enemy_count + 1)
        self.kills = 0
        self.shared_seconds = 0.
        self.crossfire_seconds = 0.
        self.death_by_zone = 0
        self.bullets = []
        self.next_id = 6000
        self.started = self.me["pos"][:]
        self.arc_s = self.cfg["weapons"]["lightning"]
        # Give half the trials a secondary weapon already acquired during the match.
        if case % 4 in (1, 2):
            arc = dict(kind="lightning", stats=self.arc_s.copy(), cooldown=0.)
            self.me["weapons"][1] = arc
            self.arcs[0] = arc
        x, y, _ = self.started
        first = self.enemy["pos"]
        heading = math.atan2(first[1]-y, first[0]-x)
        for i in range(1, self.enemy_count+1):
            point = first
            if i>1:
                for _ in range(2000):
                    angle = heading + (1 if i==2 else -1)*rng.uniform(.47,1.70)
                    distance = rng.uniform(54,113)
                    qx, qy = x+distance*math.cos(angle), y+distance*math.sin(angle)
                    if world.open_ground(qx,qy) and all(math.dist((qx,qy),p[:2])>13 for p in self.initial_targets):
                        point = (qx,qy,world.ground(qx,qy))
                        break
            if approach == "long":
                # Same-side ranged pursuit starts with at least two firing lanes.
                # Pick legal visible starts, preserving the map and policy-independent seed.
                for _ in range(4000):
                    angle = heading + rng.uniform(-.74,.74)
                    distance = rng.uniform(95.,160.)
                    qx,qy=x+distance*math.cos(angle),y+distance*math.sin(angle)
                    if not world.open_ground(qx,qy):
                        continue
                    proposed=(qx,qy,world.ground(qx,qy))
                    if (all(math.dist(proposed,p)>10 for p in self.initial_targets)
                        and world.visible(elevated(self.me,8),(qx,qy,proposed[2]+4.5))):
                        point=proposed
                        break
                else:
                    raise ValueError(f"No long approach at seed {seed}")
            self.initial_targets.append(list(point))
            has_arc = (i==self.enemy_count or (i==1 and case%4==3))
            actor = dict(self.enemy, id=(self.me["id"]+i)%16, pos=list(point), vel=[0.,0.,0.],
                         energy=100., weapons=["gun","lightning"] if has_arc else ["gun"],
                         aim=[math.atan2(y-point[1],x-point[0]),0.])
            self.actors.append(actor)
            self.guns.append(dict(self.enemy_gun, stats=self.enemy_gun["stats"].copy(),
                                  cooldown=rng.uniform(.10,.65)))
            self.arcs.append(dict(kind="lightning", stats=self.arc_s.copy(), cooldown=0.) if has_arc else None)
            self.leads.append(rng.uniform(.15,.78))
            self.lanes.append((1 if i%2==0 else -1)*(5 if i==1 else rng.uniform(15.,30.)))
            self.spray.append(random.Random(seed+31*i))
        rotation=heading+rng.uniform(-1.5,1.5)
        self.ring_from=(x+48*math.cos(rotation), y+48*math.sin(rotation))
        self.ring_to=(x+100*math.cos(rotation), y+100*math.sin(rotation))

    def zone(self):
        if self.mode==0:
            return dict(center=self.ring_from, radius=380, next_center=self.ring_to,
                        next_radius=240,shrink_start=self.start_time+40,shrink_end=self.start_time+80,dps=35)
        start = 11 if self.mode==1 else -5
        f = clamp((self.time-start)/30,0,1)
        return dict(center=[(1-f)*a+f*b for a,b in zip(self.ring_from,self.ring_to)], radius=140-70*f,
                    next_center=self.ring_to,next_radius=70,shrink_start=self.start_time+start,
                    shrink_end=self.start_time+start+30,dps=100)

    def perceived(self, viewer, point):
        p = viewer["pos"]
        d = math.dist(p, point)
        theta = math.atan2(point[1]-p[1],point[0]-p[0])
        v = self.cfg["vision"]
        return (d <= v["near_range"] or (d <= v["range"] and abs(delta(theta,viewer["aim"][0])) <
                math.radians(v["fov_deg"])/2)) and self.world.visible(elevated(viewer,8),point)

    def observation(self):
        obs = Trial.observation(self)
        alive=[]
        for i,e in enumerate(self.actors[1:],1):
            if e["hp"]<=0:
                continue
            if self.perceived(self.me,elevated(e,4.5)) or self.perceived(self.me,elevated(e,8.8)):
                self.visible_at[i]=self.time
            if self.time-self.visible_at[i] <= self.cfg["vision"]["memory_s"]:
                # Internal agent controls (weapon charge, energy) stay private.
                alive.append({k: e[k] for k in ("id","pos","vel","aim","weapons","charging","hp","max_hp","cubes","kind")})
        obs["mechs"]=alive
        obs["alive"]=(16 if self.mode==0 else 9)-sum(e["hp"]<=0 for e in self.actors[1:])
        obs["projectiles"]=[dict(id=s["id"],kind="gun",pos=s["pos"][:],vel=s["vel"][:])
                            for s in self.bullets if s["side"] and self.perceived(self.me,s["pos"])]
        obs["sounds"],self.sound_events=self.sound_events,[]
        obs["beams"],self.beam_events=self.beam_events,[]
        return obs

    def publish_sound(self, i, kind):
        if i==0:
            return
        e,p=self.actors[i],self.me["pos"]
        d=math.dist(e["pos"],p)
        s=self.cfg["sound"]
        if d<=s["range"][kind]:
            yaw=math.atan2(e["pos"][1]-p[1],e["pos"][0]-p[0])
            self.sound_events.append(dict(kind=kind,bearing=delta(yaw+self.bearing_noise.gauss(0,math.radians(s["bearing_noise_deg"])),0),
                                          dist="near" if d<s["near"] else "mid" if d<s["mid"] else "far",age=0.))

    def move_squad(self):
        living=[i for i in range(1,len(self.actors)) if self.actors[i]["hp"]>0]
        # Anyone can spot for everyone. After losing sight, flank the last known location.
        spotted=any(self.perceived(self.actors[i],elevated(self.me,4.5)) or
                    self.perceived(self.actors[i],elevated(self.me,8.8)) for i in living)
        if spotted:
            self.known=self.me["pos"][:]
            self.seen_at=self.time
            self.shared_seconds+=DT
        lanes={}
        zone=self.zone()
        for i in living:
            e=self.actors[i]
            x,y,z=e["pos"]
            goal=self.known if self.known and self.time-self.seen_at<12 else zone["next_center"]
            dx,dy=goal[0]-x, goal[1]-y
            d=max(1,math.hypot(dx,dy))
            ux,uy=dx/d,dy/d
            # Front pursuer closes aggressively; wings fan out, then converge.
            stand=25 if self.arcs[i] else 43
            lateral=self.lanes[i]*min(1,d/85)
            strafe=4.5 if int((self.time+.4*i)/2.8)%2 else -4.5
            vx=ux*clamp((d-stand)*.43,-3,11.7)-uy*clamp(lateral*.35+strafe,-8,8)
            vy=uy*clamp((d-stand)*.43,-3,11.7)+ux*clamp(lateral*.35+strafe,-8,8)
            n=math.hypot(vx,vy)
            if n>11.7:
                vx,vy=vx*11.7/n,vy*11.7/n
            a,b=e["vel"][:2]
            f=min(1,DT*58.5/(math.hypot(vx-a,vy-b) or 1))
            vx,vy=a+(vx-a)*f,b+(vy-b)*f
            sign=1 if self.lanes[i]>0 else -1
            for rad in (0,.64*sign,-.64*sign,1.22*sign,-1.22*sign,1.55*sign):
                c,s=math.cos(rad),math.sin(rad)
                wx,wy=vx*c-vy*s, vx*s+vy*c
                nx,ny=x+DT*wx,y+DT*wy
                if self.world.open_ground(nx,ny,margin=0) and abs(self.world.ground(nx,ny)-z)<1.2:
                    e["pos"]=[nx,ny,self.world.ground(nx,ny)]
                    e["vel"]=[wx,wy,(e["pos"][2]-z)/DT]
                    break
            else:
                e["vel"]=[0.,0.,0.]
            lane=(self.time-self.seen_at<.25 and math.dist(self.me["pos"],e["pos"])<=self.cfg["weapons"]["gun"]["range"]
                  and self.world.visible(elevated(e,7),elevated(self.me,4.5)))
            lanes[i]=lane
            if lane:
                lead=math.dist(e["pos"],self.me["pos"])/self.guns[i]["stats"]["speed"]*self.leads[i]
                rx,ry,rz=[a+b*lead-c for a,b,c in zip(self.me["pos"],self.me["vel"],e["pos"])]
            else:
                rx,ry,rz=dx,dy,0.
            aim=e["aim"]
            aim[0]+=clamp(delta(math.atan2(ry,rx),aim[0]),-4*DT,4*DT)
            aim[1]+=clamp(math.atan2(rz-2.5,math.hypot(rx,ry))-aim[1],-3*DT,3*DT)
        if sum(lanes.values())>=2:
            self.crossfire_seconds+=DT
        return lanes

    def damage_actor(self, source, target, amount, bearing, kind):
        a,b=self.actors[source],self.actors[target]
        if b["hp"]<=0:
            return
        rear=abs(delta(bearing,b["aim"][0]))>math.radians(self.stats["front_arc_deg"])/2
        dealt=amount*(self.stats["rear_mult"] if rear else 1)
        b["hp"]-=dealt
        self.damage[source]+=dealt
        self.last_combat[source]=self.last_combat[target]=self.time
        self.last_damage=self.time
        if source==0:
            self.events.append(dict(type="hit",target=b["id"],weapon=kind,amount=dealt,rear=rear))
            if b["hp"]<=0:
                self.kills+=1
                self.events.append(dict(type="kill",target=b["id"]))
        else:
            self.events.append(dict(type="damaged",by=a["id"],weapon=kind,amount=dealt,bearing=bearing,rear=rear))

    def lightning(self, i, pressed):
        arc=self.arcs[i]
        if not arc:
            return
        arc["cooldown"]=max(0,arc["cooldown"]-DT)
        e=self.actors[i]
        s=arc["stats"]
        if not pressed or arc["cooldown"]>1e-7 or e["energy"]<s["energy"]:
            return
        self.publish_sound(i,"lightning")
        arc["cooldown"]=s["cooldown"]
        e["energy"]-=s["energy"]
        self.last_spend[i]=self.time
        if i==0:
            self.last_spent=self.time
        others=([0] if i else [j for j in range(1,len(self.actors)) if self.actors[j]["hp"]>0])
        src=elevated(e,7)
        chain=[src]
        for jump in range(1+s["chain"]):
            candidates=[]
            for j in others:
                b=self.actors[j]
                dst=elevated(b,4.5)
                d=math.dist(src,dst)
                yaw=math.atan2(dst[1]-src[1],dst[0]-src[0])
                if ((jump or abs(delta(yaw,e["aim"][0]))<=math.radians(s["cone_deg"])) and
                    d<=(s["chain_range"] if jump else s["range"]) and self.world.visible(src,dst)):
                    candidates.append((d,j,dst))
            if not candidates:
                break
            _,j,dst=min(candidates)
            others.remove(j)
            self.damage_actor(i,j,s["damage"]*s["chain_falloff"]**jump,math.atan2(src[1]-dst[1],src[0]-dst[0]),"lightning")
            chain.append(dst)
            src=dst
        if i and len(chain)>1:
            self.beam_events.append(dict(by=e["id"],kind="lightning",path=chain,age=0.))

    def step(self, action):
        previous=[e["pos"][:] for e in self.actors]
        old_zone=self.zone_damage
        Trial.step(self,action)
        self.zone_taken[0]+=self.zone_damage-old_zone
        lanes=self.move_squad()
        for i,a in enumerate(self.actors):
            if a["hp"]<=0:
                continue
            shots_before=self.shots[i]
            gun_held=lanes.get(i,False) if i else action.get("fire",[False,False])[0]
            self.trigger(i,a,self.guns[i],gun_held,action.get("reload",False) if not i else False)
            if self.shots[i]!=shots_before:
                self.publish_sound(i,"gun")
            if i and self.time-self.last_spend[i]>=self.stats["energy_regen_delay"]:
                a["energy"]=min(100.,a["energy"]+DT*self.stats["energy_regen"])
            arc_held=(lanes.get(i,False) and math.dist(elevated(a,7),elevated(self.me,4.5))<=self.arc_s["range"]
                      if i else action.get("fire",[False,False])[1])
            self.lightning(i,arc_held)
        retained=[]
        for s in self.bullets:
            i=s["side"]
            a,v=s["pos"],s["vel"]
            b=[x+y*min(DT,s["range"]/math.hypot(*v)) for x,y in zip(a,v)]
            first=None
            for j in ([0] if i else range(1,len(self.actors))):
                if self.actors[j]["hp"]<=0:
                    continue
                t=cylinder_entry(a,b,previous[j],self.actors[j]["pos"],2.5,9)
                if t is not None and (first is None or t<first[0]):
                    first=t,j
            hit=[x+(y-x)*first[0] for x,y in zip(a,b)] if first else b
            if not self.world.visible(a,hit):
                continue
            if first:
                self.hits[i]+=1
                self.damage_actor(i,first[1],s["damage"],math.atan2(-v[1],-v[0]),"gun")
            else:
                s.update(pos=b, range=s["range"]-math.dist(a,b))
                if s["range"]>.001:
                    retained.append(s)
        self.bullets=retained
        zone=self.zone()
        for i,a in enumerate(self.actors[1:],1):
            if a["hp"]<=0:
                continue
            if math.dist(a["pos"][:2],zone["center"])>zone["radius"]:
                d=zone["dps"]*DT
                a["hp"]-=d
                self.zone_taken[i]+=d
                self.last_combat[i]=self.time
                self.death_by_zone+=a["hp"]<=0
            elif self.time-self.last_combat[i]>=self.stats["regen_delay"]:
                a["hp"]=min(a["max_hp"],a["hp"]+DT*self.stats["regen_per_s"])

    def run(self):
        while self.time < self.limit-.001 and self.me["hp"]>0 and any(e["hp"]>0 for e in self.actors[1:]):
            action=self.pilot.act(self.observation())
            for _ in range(2):
                self.step(action)
                if self.me["hp"]<=0 or all(e["hp"]<=0 for e in self.actors[1:]):
                    break
        # Count a cleared encounter as surviving the full evaluation horizon.
        survived=self.me["hp"]>0
        return dict(seed=self.seed,case=self.case,opponents=self.enemy_count,zone_mode=self.mode,
                    player_secondary=bool(self.arcs[0]),start=self.started,enemy_starts=self.initial_targets,
                    survived=survived,survival_s=self.limit if survived else round(self.time,2),
                    elapsed_s=round(self.time,2),kills=self.kills,enemy_zone_deaths=self.death_by_zone,
                    dealt=round(self.damage[0],1),incoming=round(sum(self.damage[1:]),1),
                    zone_damage=round(self.zone_taken[0],1),hp=round(max(0,self.me["hp"]),1),
                    crossfire_s=round(self.crossfire_seconds,2),crossfire_fraction=round(self.crossfire_seconds/self.time,4),
                    spotted_s=round(self.shared_seconds,2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kit",type=Path,required=True)
    p.add_argument("--bot-dir",type=Path,required=True)
    p.add_argument("--cases",type=int,default=12)
    p.add_argument("--approach",choices=("mixed","long"),default="mixed")
    p.add_argument("--first",type=int,default=0)
    p.add_argument("--split",choices=("dev","holdout"),default="dev")
    p.add_argument("--json",type=Path)
    args=p.parse_args()
    sys.path.insert(0,str(args.bot_dir.resolve()))
    world=Campus(args.kit)
    rows=[]
    for case in range(args.first,args.first+args.cases):
        seed=(15237 if args.split=="dev" else 87037)+2371*case
        trial=Squad(world,args.kit,seed,case,args.approach)
        trial.seed=seed
        row=trial.run()
        rows.append(row)
        print(json.dumps(row),flush=True)
    summary={k:round(statistics.mean(row[k] for row in rows),3) for k in (
        "survived","survival_s","kills","dealt","incoming","zone_damage","crossfire_s","crossfire_fraction")}
    print(json.dumps(summary),file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps(rows,indent=2)+"\n")


if __name__=="__main__":
    main()
