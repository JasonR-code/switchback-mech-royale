# Switchback

Switchback pilots one mech through the mechfight/1 JSON-lines interface. The root Dockerfile builds the native geometry library from source for linux/amd64. The runtime uses the Python standard library, the server-provided map and the live rule configuration. Extract this project at the root of the repository to be submitted.

## Build and verify

From this directory, run the Docker build and both replay checks with the bundled official kit.

```sh
bash validation/sandbox.sh . mechfight-kit
```

The Dockerfile pins both base images by digest. The image starts as uid and gid 65534. The official checker sends the map path in hello. The sandbox script stages readable copies of the two public map files and mounts them at /arena. Docker BuildKit and linux/amd64 support are required for building.

For local development on Linux with Python 3.10+ and g++, use these commands.

```sh
g++ -std=c++17 -O3 -fPIC -shared geometry.cpp -o geometry.so
python3 mechfight-kit/check/check.py -- python3 -u main.py
PYTHONPATH=. python3 -m unittest discover -s validation -v
python3 validation/stress.py
python3 validation/arena_trials.py --kit mechfight-kit --bot-dir . --cases 12 --split holdout --policies starter pilot no-route
python3 validation/skirmish.py --kit mechfight-kit --bot-dir . --cases 12 --split holdout
```

## How it plays

Practice points depend on how many mechs die before the player. The 15 house mechs share information and do not attack one another. Switchback looks for early cubes, weapons, and isolated opponents, then evaluates whether a second attacker, an HP deficit, or an incoming zone makes the current engagement too expensive. It uses the same observation-based policy for a free-for-all. The hello seed varies scouting and strafing patterns. The policy has no match seeds or opponent implementation.

* **Strategy.** Remembers observed pickups and contacts. Scores candidate destinations by arrival time relative to the shrinking circle, enemy firing angles, cover, item value and recent visits. A landed supply drop can restore all HP and energy, so the policy values uncontested capture more highly when damaged. It avoids chasing distant crates while trying to regenerate. Dealing damage also restarts the regeneration delay.
* **Map and routes.** Reads the official terrain and prism footprints, holes, floors and ceilings. A layered four-metre graph supports bounded A* search and reuses routes. A shorter-horizon controller considers acceleration, cylinder clearance, ledges, energy, direct fire and incoming shells. Repeated observations of little displacement during a planned journey trigger a short jet attempt.
* **Fire control.** Scores compatible firing directions for both slots. Uses gun intercepts, gravity-aware mortar roots and arc clearance, charge-aware laser release, and lightning range and cone checks. Enemy torso aim, HP and weapon interactions influence target choice. The bot can keep its torso facing a pursuer while moving toward cover.
* **Resources.** Rates cube clusters and upgrade thresholds, checks both vertical and horizontal pickup distance, and accounts for the cost of replacing an equipped weapon. It aims to sustain the arm gun alongside a secondary. Upgrade and weapon priorities are hand-tuned estimates.

## Evidence and remaining uncertainty

Read validation/RESULTS.md for measured replay timing, controlled experiments, held-out results, and limitations. Raw per-scenario results and checker output are in validation/results. No official practice run has been submitted. The included starter kit is the supplied public competition material.

[Official track](https://www.joinbuilders.org/buildathon/tracks/builders)
