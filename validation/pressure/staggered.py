"""Controlled 28-second encounter sensitivity. These encounters do not award placement."""
import argparse
import json
import sys
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--bot', required=True, type=Path)
p.add_argument('--harness', required=True, type=Path)
p.add_argument('--cases', default=24, type=int)
args = p.parse_args()
sys.path[:0] = [str(args.bot.resolve()), str((args.harness/'validation').resolve())]
from arena import Arena
from squad_trials import Campus, Squad

class Staggered(Squad):
    def __init__(self, *params, leading):
        super().__init__(*params)
        self.leading = leading
        self.leads[1:] = [leading] * self.enemy_count
        self.reported = set()
        self.last = {}
        self.second = None
        self.unreported = 0.

    def move_squad(self):
        # Same spawn and equipment in both aim models. Rivals join in waves.
        join = 2. + self.case % 4
        n = 1 + int(self.time >= join) + int(self.time >= join + 4.)
        alive = [i for i in range(1, min(n, self.enemy_count)+1) if self.actors[i]['hp'] > 0]
        return super().move_squad(alive)

    def observation(self):
        obs = super().observation()
        self.reported = {e['id'] for e in obs['mechs']}
        return obs

    def damage_actor(self, source, target, amount, bearing, kind):
        hp = self.me['hp']
        super().damage_actor(source, target, amount, bearing, kind)
        if target == 0 and hp > 0:
            ident = self.actors[source]['id']
            if ident not in self.reported:
                self.unreported += hp - self.me['hp']
            if self.second is None and any(i != ident and self.time-t <= 3. for i,t in self.last.items()):
                self.second = self.time
            self.last[ident] = self.time

kit = args.harness/'mechfight-kit'
world = Campus(kit)
rays = Arena(kit/'arena')
assert rays.handle
world.visible = rays.clear
for case in range(args.cases):
    for lead in (.15,.90):
        seed = 748141 + 3191*case
        match = Staggered(world, kit, seed, case, leading=lead)
        match.seed = seed
        row = match.run()
        row.update(lead=lead, second=match.second, unreported_damage=round(match.unreported,2))
        print(json.dumps(row), flush=True)
