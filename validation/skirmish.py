"""Independent, short gun-only campus skirmishes. This is a scripted opponent probe.
Usage: python skirmish.py --kit ... --bot-dir ... --split dev --cases 8
Uses official gun/energy/motion constants; no house bot logic, other mechs, foliage or loot.
"""
import argparse
import collections
import json
import math
import random
import statistics
import sys
from pathlib import Path

from arena_trials import DT, Campus, Trial, clamp, delta, integrated, load_starter


def cylinder_entry(start, end, feet, new_feet, radius, height):
    """Fraction of a tick at entry into a linearly moving vertical cylinder."""
    ax, ay, az = (x-y for x,y in zip(start, feet))
    dx, dy, dz = ((q-p)-(v-u) for p,q,u,v in zip(start,end,feet,new_feet))
    a = dx*dx+dy*dy
    b = ax*dx+ay*dy
    c = ax*ax+ay*ay-radius*radius
    lo, hi = 0., 1.
    if a > 1e-12:
        disc = b*b-a*c
        if disc < 0:
            return None
        r = math.sqrt(disc)
        lo, hi = max(lo,(-b-r)/a), min(hi,(-b+r)/a)
    elif c>0:
        return None
    if abs(dz)>1e-12:
        v = sorted((-az/dz,(height-az)/dz))
        lo, hi = max(lo,v[0]), min(hi,v[1])
    elif az < 0 or az > height:
        return None
    return lo if lo <= hi else None


class Skirmish(Trial):
    def __init__(self, world, kit, factory, seed):
        super().__init__(world, kit, factory, 'loot', seed, False)
        self.family = 'duel'
        rng = random.Random(seed+6931)
        self.spray = [random.Random(seed+1),random.Random(seed+2)]
        self.start_time = 45.
        self.goal = self.me['pos'][:]
        found = False
        for _ in range(12000):
            x0,y0,x1,y1 = world.bounds
            x,y = rng.uniform(x0+50,x1-50), rng.uniform(y0+50,y1-50)
            if not world.open_ground(x,y):
                continue
            angle = rng.uniform(-math.pi,math.pi)
            distance = rng.uniform(58,102)
            ux,uy = math.cos(angle),math.sin(angle)
            ex,ey=x+ux*distance,y+uy*distance
            if not world.open_ground(ex,ey):
                continue
            a,b=(x,y,world.ground(x,y)),(ex,ey,world.ground(ex,ey))
            if not world.visible((x,y,a[2]+7), (ex,ey,b[2]+4.5)):
                continue
            if not all(world.open_ground(ex-uy*t,ey+ux*t) for t in range(-14,15,3)):
                continue
            found = True
            break
        if not found:
            raise ValueError(seed)
        self.me.update(pos=list(a),aim=[angle,0])
        self.initial_start = list(a)
        self.goal=list(b)
        self.loot_circle=(x,y)
        self.enemy=dict(id=(self.me['id']+1)%16,kind='mech',weapons=['gun'],charging=False,
                        pos=list(b),vel=[0,0,0],hp=1400,max_hp=1400,cubes=0,aim=[delta(angle+math.pi,0),0])
        self.enemy_gun=dict(stats=self.cfg['weapons']['gun'],ammo=self.cfg['weapons']['gun']['mag'],
                            cooldown=0.,reload=0.)
        self.heading=angle
        self.clock_phase=rng.uniform(0,2.5)
        self.period=rng.uniform(2.0,3.2)
        self.lead_factor=rng.choice([0.,.45,.75])
        self.bullets=[]
        self.shots=[0,0]
        self.hits=[0,0]
        self.damage=[0.,0.]
        self.last_seen=-math.inf
        self.last_enemy_combat=-math.inf
        self.last_sound=-math.inf
        self.next_id=1

    def observation(self):
        obs=super().observation()
        p,e=self.me['pos'], self.enemy['pos']
        bearing=math.atan2(e[1]-p[1], e[0]-p[0])
        def visible(b):
            d=math.dist(p,b)
            theta=math.atan2(b[1]-p[1], b[0]-p[0])
            return (d <= 45 or (d <= 200 and abs(delta(theta,self.me['aim'][0]))<math.pi/3)) and self.world.visible(
                (*p[:2],p[2]+8),b)
        if visible((*e[:2],e[2]+4.5)) or visible((*e[:2],e[2]+8.9)):
            self.last_seen=self.time
        obs['mechs']=[self.enemy] if self.time-self.last_seen<=5 else []
        obs['projectiles']=[dict(id=s['id'],kind='gun',pos=s['pos'][:],vel=s['vel'][:]) for s in self.bullets
                            if s['side']==1 and visible(s['pos'])]
        obs['sounds'] = ([dict(kind='gun', bearing=bearing,dist='near' if math.dist(p,e)<60 else 'mid',
                              age=max(0,self.time-self.last_sound))]
                         if self.time-self.last_sound<.1 else [])
        return obs

    def enemy_step(self):
        e,p=self.enemy,self.me
        x,y,z=e['pos']
        # A hand-scripted pursuit: weave, close to ~65m, and stop at obstacles.
        dx,dy = p['pos'][0]-x,p['pos'][1]-y
        d = max(1.,math.hypot(dx,dy))
        ux,uy=dx/d,dy/d
        strafe = 9 if int((self.time+self.clock_phase)/self.period)%2==0 else -9
        vx=ux*clamp((d-65)*.22,-3,7)-uy*strafe
        vy=uy*clamp((d-65)*.22,-3,7)+ux*strafe
        ox,oy=e['vel'][:2]
        f=min(1.,58.5*DT/(math.hypot(vx-ox,vy-oy) or 1))
        vx,vy=ox+f*(vx-ox),oy+f*(vy-oy)
        nx,ny=x+vx*DT,y+vy*DT
        if self.world.open_ground(nx,ny,margin=0):
            e['pos']=[nx,ny,self.world.ground(nx,ny)]
            e['vel']=[vx,vy,(e['pos'][2]-z)/DT]
        else:
            e['vel']=[0.,0.,0.]
        seconds=math.dist(e['pos'],p['pos'])/self.enemy_gun['stats']['speed']*self.lead_factor
        lead=[a+b*seconds-c for a,b,c in zip(p['pos'],p['vel'],e['pos'])]
        lead[2] += 4.5-7
        yaw=math.atan2(lead[1],lead[0])
        pitch=math.atan2(lead[2],math.hypot(*lead[:2]))
        e['aim'][0] += clamp(delta(yaw,e['aim'][0]),-4*DT,4*DT)
        e['aim'][1] += clamp(pitch-e['aim'][1],-3*DT,3*DT)
        return self.world.visible((*e['pos'][:2],e['pos'][2]+7),(*p['pos'][:2],p['pos'][2]+4.5))

    def trigger(self,side,actor,gun,pressed,reload):
        w=gun['stats']
        gun['cooldown']=max(0.,gun['cooldown']-DT)
        if gun['reload']>0:
            gun['reload']=max(0.,gun['reload']-DT)
            if gun['reload'] < 1e-7:
                gun.update(ammo=w['mag'], reload=0.)
            return
        if reload and gun['ammo']<w['mag'] or gun['ammo']==0:
            gun['reload']=w['reload']
            return
        if not pressed or gun['cooldown']>1e-7:
            return
        gun['ammo']-=1
        gun['cooldown']=w['cooldown']
        if not gun['ammo']:
            gun['reload']=w['reload']
        noise=self.spray[side]
        yaw=actor['aim'][0]+math.radians(noise.gauss(0,w['spread_deg']))
        pitch=actor['aim'][1]+math.radians(noise.gauss(0,w['spread_deg']))
        direction=[math.cos(yaw)*math.cos(pitch),math.sin(yaw)*math.cos(pitch), math.sin(pitch)]
        start=[*actor['pos'][:2],actor['pos'][2]+7]
        origin=[a+3*b for a,b in zip(start,direction)]
        self.shots[side] +=1
        if side:
            self.last_sound=self.time
        if not self.world.visible(start,origin):
            return
        self.bullets.append(dict(side=side,id=self.next_id,pos=origin,vel=[v*w['speed'] for v in direction],
                                 range=w['range'], damage=w['damage']))
        self.next_id+=1

    def step(self,action):
        old_pos=[a['pos'][:] for a in (self.me,self.enemy)]
        super().step(action)
        enemy_fire=self.enemy_step()
        self.trigger(0,self.me,self.me['weapons'][0],action.get('fire',[False,False])[0],action.get('reload',False))
        self.trigger(1,self.enemy,self.enemy_gun,enemy_fire,False)
        retained=[]
        for s in self.bullets:
            owner=s['side']
            actor = self.me if owner else self.enemy
            a,v=s['pos'],s['vel']
            travel=min(DT,s['range']/math.hypot(*v))
            b=[x+y*travel for x,y in zip(a,v)]
            entry=cylinder_entry(a,b,old_pos[1-owner],actor['pos'],2.5,9)
            hit=[x+(y-x)*entry for x,y in zip(a,b)] if entry is not None else b
            if not self.world.visible(a,hit):
                continue
            if entry is not None:
                bearing=math.atan2(-v[1],-v[0])
                rear=abs(delta(bearing,actor['aim'][0]))>math.pi/2
                damage=s['damage']*(1.5 if rear else 1)
                actor['hp'] -= damage
                self.hits[owner]+=1
                self.damage[owner]+=damage
                self.last_damage=self.last_enemy_combat=self.time
                event=(dict(type='damaged',by=self.enemy['id'],amount=damage,weapon='gun',bearing=bearing,rear=rear)
                       if owner else dict(type='hit',target=self.enemy['id'],amount=damage,weapon='gun',rear=rear))
                self.events.append(event)
            else:
                s.update(pos=b, range=s['range']-math.dist(a,b))
                if s['range']>.001:
                    retained.append(s)
        self.bullets=retained
        if self.time-self.last_enemy_combat>=5:
            self.enemy['hp']=min(1400,self.enemy['hp']+45*DT)

    def run(self):
        while self.time<24-.001 and min(self.enemy['hp'],self.me['hp'])>0:
            action=self.pilot.act(self.observation())
            self.step(action)
            if min(self.enemy['hp'],self.me['hp'])>0:
                self.step(action)
        return dict(eliminated=self.enemy['hp']<=0, survived=self.me['hp']>0, time=round(self.time,2),
                    damage_dealt=round(self.damage[0],1), damage_taken=round(self.damage[1],1),
                    shots=self.shots[0], hits=self.hits[0], opponent_lead=self.lead_factor)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit',type=Path,required=True)
    parser.add_argument('--bot-dir',type=Path,required=True)
    parser.add_argument('--policies',choices=['starter','pilot'],nargs='+',default=['starter','pilot'])
    parser.add_argument('--cases',type=int,default=8)
    parser.add_argument('--split',choices=['dev','holdout'],default='dev')
    parser.add_argument('--json',type=Path)
    args=parser.parse_args()
    sys.path.insert(0,str(args.bot_dir.resolve()))
    factories={'starter':load_starter(args.kit),'pilot':integrated}
    world=Campus(args.kit)
    results=[]
    groups=collections.defaultdict(list)
    for i in range(args.cases):
        seed=(8459 if args.split=='dev' else 80557)+113*i
        for policy in args.policies:
            trial=Skirmish(world,args.kit,factories[policy],seed)
            row=dict(policy=policy,seed=seed,start=trial.initial_start,enemy_start=trial.goal,**trial.run())
            print(json.dumps(row),flush=True)
            results.append(row)
            groups[policy].append(row)
    for policy,rows in groups.items():
        print(f"{policy} ({len(rows)}): eliminated {sum(x['eliminated'] for x in rows)}, "
              f"survived {sum(x['survived'] for x in rows)}, mean damage "
              f"{statistics.mean(x['damage_dealt'] for x in rows):.1f} dealt / "
              f"{statistics.mean(x['damage_taken'] for x in rows):.1f} taken",file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps(results,indent=2)+'\n')


if __name__=='__main__':
    main()
