# Snowball candidate (branch `claude-snowball`, built on `aa40f9e` = official 4.63)

Gameplay change: **`strategy.py` only**. Combat timing, mortar drift and rear-arc code are byte-identical to 4.63. `SNOWBALL = False` restores 4.63 behaviour exactly.

## What the 4.63 strategy does (from the code)

- **Never pursues.** No destination category targets an enemy. While a rival is visible the bot holds a position about 75 m from it; when the rival breaks sight nothing draws us toward it.
- **Retreats from bystanders.** The escape rules count `len(visible) > 1` and `aimed >= 2`, where "aimed" means `danger > 0.26`, and danger is mostly proximity. A rival 150 m away facing *away* scores about 0.30. Two visible rivals that aren't engaging us therefore force a withdrawal. In the snowball lab the 4.63 bot had escape set on **80%** of decisions, with "withdraw" as the goal on 60%.
- **Undervalues kill cubes.** The cubes a victim drops are only valued once seen. In the snowball lab the 4.63 bot collected 0.3–1.1 cubes per case despite 1–2.5 kills.
- Upgrade priorities, the gun-magazine preference and loot valuation were checked in the structural audit and look sound.

Evidence for the change: the track page says house bots "share vision, never fight each other, and hunt you weakest first (one early, more as you thin them out, all of them late)". A visible house bot looking elsewhere is plausibly not hunting us yet.

## The change

While fewer than 8 mechs are dead and t < 300 s (the "snowball phase"):

1. **Bystander-aware escape.** In the existing escape conditions, `len(visible)` and `aimed` count only *engaging* rivals: aim within about 25° of us (cos > 0.9), within 60 m, or hit us in the last 3 s. All other escape rules (low HP, pressure) are unchanged. After the snowball phase, the 4.63 rules apply.
2. **Spoils.** After a `kill` event, the victim's last position becomes a destination (base 52, decaying 2 per second, for 15 s), so we collect its cubes (death drop = its cubes + 2).

Also implemented but **disabled** by their constants, because the ablation showed no added kills and slightly worse survival:
- closer fight range (48 m instead of 75 m);
- a finish commitment that suppresses escape when the only rival is at ≤35% HP;
- hunting wounded rivals that break sight.

## Snowball lab (`combat_snowball.py`), matched seeds, 160 cases per row, vs unchanged 4.63

The lab: full `main.Pilot` vs 6 tiered rivals over 120 s, with escalation (one hunter, plus one per kill), withdraw-and-regenerate below 35% HP, 2 cubes per kill, our regeneration, and 200 m vision. Every rival behaviour is an **assumption**, not a measurement of house bots. The lab has no map or cover, so rival damage is scaled to stand in for cover; "np" means a rival we shoot does not start hunting.

| Split / setting | Kills (= outlasted) | First kill | Deaths < 60 s | Alive (120 s cap) | Cubes |
|---|---|---|---|---|---|
| holdout ×0.5 | 1.29 → **2.13** (+0.84 [+0.59, +1.09]) | −27 s | −0.02 | +3.2 s | +1.2 |
| holdout ×0.5 np | 2.50 → **3.11** (+0.61) | −12 s | **+0.11** [+0.03, +0.19] | **−7.0 s** | +1.7 |
| holdout ×0.3 | 2.11 → **3.17** (+1.07) | −21 s | −0.03 | +6.1 s | +2.0 |
| fresh ×0.5 | 1.24 → **2.01** (+0.76) | −25 s | +0.02 | +3.3 s | +1.2 |
| fresh ×0.5 np | 2.40 → **3.09** (+0.69) | −12 s | **+0.10** [+0.02, +0.19] | +0.2 s | +1.6 |
| fresh ×0.3 | 1.88 → **3.16** (+1.28) | −25 s | −0.06 | +6.9 s | +2.0 |

- **Ablation (dev):** the bystander rule alone gives essentially the whole gain. Adding the closer range, finish commitment and hunting changed kills by less than 0.1 and reduced time alive.
- **Pursuit check:** in `combat_squad.py --pilot`, where every rival aims at us, results are **bit-identical** to 4.63 (holdout, 320 cases). With real crossfire the bot still withdraws as before.
- **Decisions really change:** in the probe, escape fell from 80% to 58% of decisions, anchor goals rose from 34% to 50%, and spoils goals made up 12%.

## Risks and limitations

- The gain depends on house bots that face away not shooting us. If they turn quickly, or shared vision makes them engage at once, we stay in fights the 4.63 bot would have left.
- When bystanders never retaliate, early deaths rose by about 0.10 per case: we fight the lone hunter instead of withdrawing.
- There is no map, cover, zone, loot, drones, upgrades, sound or squad intelligence. The 4.63 bot's real kill rate (Codex's simulations: about 4.7 per match) is far above this lab's 1–2.5, so absolute numbers are not comparable.
- Docker and real-map tests were not run on this host.

## Validation

70 tests pass, except the 3 that need `geometry.so`. The 7 new `test_snowball.py` tests cover the bystander rule, engaged and close rivals, recent attackers, the late-game revert, the switch-off and spoils; with `SNOWBALL = False` the bystander and spoils tests fail as expected. Official `check.py`: PASS, 300/300, p99 0.5 ms. Dense timing: p50 1.57 ms (4.63: 1.53), 0 over 50 ms.
