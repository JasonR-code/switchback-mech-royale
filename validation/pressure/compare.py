"""Audit the four paired policies and emit per-start results and seed-clustered intervals."""
import argparse
import csv
import json
from pathlib import Path
from random import Random
from statistics import mean

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('directory', type=Path)
p.add_argument('--prefix',default='fresh')
p.add_argument('--output',type=Path,required=True)
args=p.parse_args()
modes=('direct','routed')
labels='ABCD'

def read(name):
    rows = [json.loads(s) for s in (args.directory/name).read_text().splitlines()]
    result = {r['seed']:r for r in rows}
    assert len(result)==len(rows)>0
    return result

def average(rows, key):
    values=[r[key] for r in rows if r[key] is not None]
    return round(mean(values),3) if values else None

def metrics(rows):
    at_risk=[r for r in rows if r['second_impact'] is not None]
    past=[r for r in rows if r['second_at'] is not None]
    return dict(n=len(rows), placement=average(rows,'prior_deaths'),
        deaths_lt60=sum(r['elapsed_s']<60 and not r['survived'] for r in rows),
        bottom3=sum(r['prior_deaths']<=2 for r in rows), kills=average(rows,'kills'),
        equipped=sum(r['first_secondary'] is not None for r in rows),
        acquisition_s=average(rows,'first_secondary'), zone=average(rows,'zone_damage'),
        unseen=average(rows,'unreported_damage'), incoming=average(rows,'incoming'),
        crossfire_s=average(rows,'crossfire_s'), second=len(at_risk),
        seconds_of_12=average(at_risk,'impact12_alive'),
        dead_within_12=sum(r['impact12_alive'] < 12 for r in at_risk),
        after_observed_damage=average(past,'post12_damage'),
        after_observed_crossfire=average(past,'post12_crossfire'),
        cover_activated=sum(bool(r['cover_frames']) for r in rows),
        steer_activated=sum(bool(r['bearing_frames']) for r in rows))

predictions = {(label,mode):read(f'{args.prefix}-{label}-{mode}.jsonl') for label in labels for mode in modes}
all_seeds=sorted(predictions['A','direct'])
baseline={mode:predictions['A',mode] for mode in modes}
stored={mode:read(f'base-{mode}.jsonl') for mode in modes} if args.prefix=='fresh' else None
lines=[]
summary={}
for label in labels:
    scores={}
    for mode in modes:
        reference, variant=baseline[mode],predictions[label,mode]
        assert sorted(reference)==sorted(variant)==all_seeds
        for seed in all_seeds:
            a,b=reference[seed],variant[seed]
            for key in ('case','start','enemy_starts','phase','zone_aware','arsenal','full','opponents'):
                assert a[key]==b[key], (label,mode,seed,key)
            assert len(a['enemy_starts'])==15 and a['full'] and a['zone_aware']==(mode=='routed')
            assert not (a['censored'] or b['censored'])
            assert a['second_impact']==b['second_impact'], (label,mode,seed,'initial trigger changed')
            if stored:
                assert all(a[k]==v for k,v in stored[mode][seed].items()), (mode,seed,'baseline replay mismatch')
            lines.append(dict(policy=label,model=mode,seed=seed,baseline_outlasted=a['prior_deaths'],
                outlasted=b['prior_deaths'],delta=b['prior_deaths']-a['prior_deaths'],elapsed=b['elapsed_s'],
                second=b['second_impact'],post12_alive=b['impact12_alive'],post12_damage=b['post12_damage'],
                incoming=b['incoming'],unreported=b['unreported_damage'],crossfire=b['crossfire_s'],
                secondary=b['first_secondary'],kills=b['kills'],zone_damage=b['zone_damage'],
                cover_ticks=b['cover_frames'],steer_ticks=b['bearing_frames']))
        scores[mode]=metrics(list(variant.values()))
    all_rows=[r for m in modes for r in predictions[label,m].values()]
    scores['all']=metrics(all_rows)
    changes=[l['delta'] for l in lines if l['policy']==label]
    pairs=[mean(predictions[label,m][s]['prior_deaths']-baseline[m][s]['prior_deaths'] for m in modes) for s in all_seeds]
    rng=Random(4027)
    boot=sorted(mean(rng.choices(pairs,k=len(pairs))) for _ in range(10000))
    scores['change']=dict(pooled=round(mean(pairs),3),interval=[round(boot[249],3),round(boot[9749],3)],
        better=sum(d>0 for d in changes),tied=changes.count(0),worse=sum(d<0 for d in changes),
        worst=min(changes),best=max(changes))
    summary[label]=scores
with args.output.open('w',newline='') as f:
    out=csv.DictWriter(f,lines[0],lineterminator='\n')
    out.writeheader()
    out.writerows(lines)
print(json.dumps(summary,indent=2))
