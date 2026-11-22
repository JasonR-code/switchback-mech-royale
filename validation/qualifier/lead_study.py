"""Paired shot evaluation. Synthetic model draws and the public recording are independent."""
import argparse
import gzip
import json
import math
from pathlib import Path
import random
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/"validation")]
from arena import Arena
from combat import gun_solution
from gun_tracking import GunTrack


def clip(x,a,b):
    return max(a,min(b,x))


def synthetic(style, seed):
    r=random.Random(seed)
    T=.1
    n=110
    heading=r.uniform(-math.pi,math.pi)
    phi=r.uniform(-math.pi,math.pi)
    speed=r.uniform(7,18)
    forward=r.uniform(-3,5)
    rate=r.uniform(.5,2.7)*r.choice((-1,1))
    half=r.uniform(.4,1.6)
    accel=r.uniform(35,58.5)
    initial=r.uniform(40,185)
    own_speed=r.uniform(0,17)
    own_phase=r.uniform(-3,3)
    ownpos=(0.,0.,0.)
    pos=(initial*math.cos(phi),initial*math.sin(phi),0.)
    vx,vy=speed*math.cos(heading),speed*math.sin(heading)
    if style in ("stationary","start-stop"):
        vx=vy=0.
    rows=[]
    next_change=half
    polarity=1
    parked=True
    for i in range(n):
        t=i*T
        ownvel=(own_speed*math.cos(own_phase+.22*t),own_speed*math.sin(own_phase+.22*t),0.)
        rows.append((t,ownpos,ownvel,pos,(vx,vy,0.),(i%3)*.04))
        if t>=next_change:
            polarity*=-1
            parked = not parked
            if not parked and style=="start-stop":
                heading+=r.uniform(-2.2,2.2)
            next_change+=half*r.uniform(.6,1.45)
        if style=="stationary":
            tx=ty=0.
        elif style=="straight":
            tx,ty=speed*math.cos(heading),speed*math.sin(heading)
        elif style=="turn":
            tx,ty=speed*math.cos(heading+rate*t),speed*math.sin(heading+rate*t)
        elif style=="strafe":
            tx,ty=(forward*math.cos(heading)-polarity*speed*math.sin(heading),
                   forward*math.sin(heading)+polarity*speed*math.cos(heading))
        else:
            tx,ty=(0.,0.) if parked else (speed*math.cos(heading),speed*math.sin(heading))
        f=min(1.,accel*T/max(.001,math.hypot(tx-vx,ty-vy)))
        old=(vx,vy)
        vx+=f*(tx-vx)
        vy+=f*(ty-vy)
        pos=(pos[0]+.5*T*(old[0]+vx),pos[1]+.5*T*(old[1]+vy),0.)
        ownpos=(ownpos[0]+T*ownvel[0],ownpos[1]+T*ownvel[1],0.)
    return rows


def official(root):
    with gzip.open(root/"mechfight-kit/check/stream.jsonl.gz","rt") as f:
        rows=[]
        for o in map(json.loads,f):
            if o["type"]!="obs": continue
            me=o["self"]
            e=next((e for e in o["mechs"] if e["kind"]=="mech" and e["id"]==10),None)
            if not e: continue
            rows.append((o["t"],me["pos"],me["vel"],e["pos"],e["vel"],me["weapons"][0]["cooldown"]))
        return [r for r in rows if 4.<r[0]<13.5], [r for r in rows if 17.<r[0]<26.2]


def evaluate(rows, seed, real, arena):
    rng=np.random.default_rng(seed)
    tracker=GunTrack()
    sample=[]
    prev=None
    for i,(now,p,ownvel,foe,v,cd) in enumerate(rows):
        d=np.array(foe)-p
        d[2]+=4.59-7
        r=math.hypot(*d[:2])
        dt=now-prev[0] if prev else 0
        conf=1.
        if 0<dt<.25:
            dv=math.hypot(v[0]-prev[1][0],v[1]-prev[1][1])
            conf=1-.38*clip((dv/dt-12)/50,0,1)
        base=(conf*v[0],conf*v[1],v[2])
        prev=now,v
        H=clip(r/252,.14,.88)
        pred=tracker.step(now,foe,v,base,H,(d[0]/max(r,.001),d[1]/max(r,.001)))
        if i<1 or i+11>=len(rows) or r<20 or r>217 or (real and cd>.10001): continue
        if abs(rows[i+10][0] - now-1.)>.03: continue
        wait=.05 if cd<=.05 else .10
        # Midpoint timing is held fixed across policies, and the same 12
        # Gaussian samples resolve hits using the observed future trajectory.
        delay=wait-.025
        own=np.array(p)+(np.array(rows[i+1][1])-p)*(delay/.1)
        own[2]+=7.
        offsets=rng.normal(0.,math.radians(.6),(12,2))
        path=np.array([r[3] for r in rows[i:i+12]])
        got=[]
        for vel in (base,pred):
            extrap=np.array(vel)
            extrap[2]*=min(1.,.25*252/max(1,r))
            target=d+np.array(vel)*.025
            sol=gun_solution(target,extrap,252,3.)
            if sol is None or sol[2]*252>230: got.append(0);continue
            yaw,pitch,_=sol
            endpoint=np.array(p)+(0,0,7)+target+extrap*sol[2]
            if real and not arena.clear((p[0],p[1],p[2]+7),endpoint):
                endpoint[2]+=3.15
                if not arena.clear((p[0],p[1],p[2]+7),endpoint):
                    got.append(0);continue
                pitch=math.atan2(endpoint[2]-p[2]-7,math.hypot(endpoint[0]-p[0],endpoint[1]-p[1]))
            # Intersect horizontal disk entry/exit times with the vertical
            # slab for every segment of the moving target's swept cylinder.
            ys=yaw+offsets[:,0]; ps=pitch+offsets[:,1]
            units=np.array([np.cos(ys)*np.cos(ps),np.sin(ys)*np.cos(ps),np.sin(ps)]).T
            t0=np.arange(10)*.1
            t1=np.arange(1,11)*.1
            t0[0]=delay;t1=np.minimum(t1,230/252+delay)
            valid=t0<t1
            t0=t0[valid];t1=t1[valid]
            begin=path[:len(t0)].copy();begin[0]+=(path[1]-path[0])*(delay/.1)
            end=path[1:1+len(t0)].copy()
            k=len(end)-1;end[k]=path[k]+(path[k+1]-path[k])*((t1[k]-.1*k)/.1)
            a=own[None,None,:]+(3+(t0-delay)*252)[None,:,None]*units[:,None,:]-begin
            b=own[None,None,:]+(3+(t1-delay)*252)[None,:,None]*units[:,None,:]-end
            dd=b-a
            dot=np.sum(a[:,:,:2]*dd[:,:,:2],axis=2)
            norm=np.maximum(1e-12,np.sum(dd[:,:,:2]**2,axis=2))
            c=np.sum(a[:,:,:2]**2,axis=2)-2.5**2
            disc=dot*dot-norm*c
            root=np.sqrt(np.maximum(disc,0))
            lo=np.maximum(0.,(-dot-root)/norm)
            hi=np.minimum(1.,(-dot+root)/norm)
            vz=dd[:,:,2]
            safe_vz=np.where(abs(vz)<1e-10,1.,vz)
            z1,z2=-a[:,:,2]/safe_vz,(9-a[:,:,2])/safe_vz
            level=abs(vz)<1e-10
            lo=np.maximum(lo,np.where(level,-np.inf,np.minimum(z1,z2)))
            hi=np.minimum(hi,np.where(level,np.inf,np.maximum(z1,z2)))
            contact=(disc>=0)&(lo<=hi)&(~level|((a[:,:,2]>=0)&(a[:,:,2]<=9)))
            hits=np.any(contact,axis=1)
            if real:
                for n in np.flatnonzero(hits):
                    seg=np.argmax(contact[n])
                    at=t0[seg]+lo[n,seg]*(t1[seg]-t0[seg])
                    hits[n]=arena.clear(own,own+units[n]*(3+252*(at-delay)))
            got.append(int(np.sum(hits)))
        sample.append(got)
    return [sum(x[j] for x in sample) for j in (0,1)] + [12*len(sample)]


def main():
    p=argparse.ArgumentParser();p.add_argument('--seeds',type=int,default=12);p.add_argument('--base',type=int,default=15801);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    allout={}
    for style in ('stationary','straight','turn','strafe','start-stop'):
        vals=[]
        for i in range(a.seeds):
            seed=a.base+i*8059
            vals.append(evaluate(synthetic(style,seed),seed+231,False,None))
        allout[style]=vals
    arena=Arena(ROOT/'mechfight-kit/arena');assert arena.handle
    for j,panel in enumerate(official(ROOT)):
        allout['archived_'+('early','late')[j]]=[evaluate(panel,198117,True,arena)]
    a.out.write_text(json.dumps(allout))
    for style,vals in allout.items():
        h,c,n=np.sum(vals,axis=0)
        print(style,h,c,n,round(100*(c-h)/max(n,1),2),flush=True)


if __name__=='__main__':
    main()
