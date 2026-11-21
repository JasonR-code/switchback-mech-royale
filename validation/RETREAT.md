# Switchback retreat candidate

The official 48-match practice score for parent commit eecc4f9 is 4.27/15. Only Builders can measure the new candidate’s placement score. The baseline and candidate faced identical starting positions and opponent parameters in each paired local trial.

## Reproduced failures

With full HP, no cover, and two aimed guns at (100, ±20) metres, seed 20, the baseline marked the situation as an escape and selected its own position. With the same shooters at (150, ±20), the baseline did not enter escape and chose (42.8, 10.3), closer to both shooters. The candidate selected (−8.9, −13.3) and (−8.0, 13.8), respectively. The regression tests check separation from each shooter, including mirrored starts, plus the actual movement command from the main loop. Other tests cover opponents on opposite sides, a three-way flank, a walkable destination behind an impassable low wall, and a shrinking final ring.

Under overlapping fire, strategy now considers reachable retreat legs and the firing lanes encountered on the way to each destination. It keeps a planned route into shelter unless a direct escape removes more firing lanes or the exposed anchor fails to open separation. The controller can move sideways while returning fire. The navigation map accounts for changes in the mech’s cylinder size after collecting cubes. Controlled geometry tests cover narrow passages, headroom, and excessive uphill grades. Combat tests cover lightning intercepted by a nearer object and mortar damage interrupting health recovery.

## Pursuit experiments

On 12 mixed development starts, the baseline averaged 10.55 seconds alive. The interrupted combined changes averaged 6.92 seconds. An alternative that prioritized new cover routes averaged 8.82 seconds. The selective retreat and transverse-motion prototype averaged 11.14 seconds. We retained the selective override and tested the resulting candidate on separate starts.

The following results use 20 paired held-out campus starts per condition. Each run ends after 28 seconds or earlier on elimination. Time alive is capped at 28 seconds. Crossfire measures the mean fraction of each encounter with at least two opponent firing lanes. Both conditions reuse the same 20 seeds with different opponent placements.

| Synthetic condition | Policy | Mean time alive | Survived | Time exposed to crossfire | Mean zone damage |
|---|---|---:|---:|---:|---:|
| Mixed approaches | Baseline | 10.64 s | 2/20 | 65.3% | 0 HP |
| Mixed approaches | Candidate | 11.78 s | 2/20 | 57.7% | 9.5 HP |
| 95–160 m approaches | Baseline | 13.93 s | 3/20 | 62.6% | 7.0 HP |
| 95–160 m approaches | Candidate | 16.72 s | 5/20 | 51.3% | 0 HP |

On mixed approaches, the candidate lived longer on 11 starts, tied on six and died earlier on three. The median paired improvement was 0.05 seconds. At long range it lived longer on 15 starts, tied on four and died earlier on one. The median paired improvement was 0.83 seconds. Mixed-approach survival to the time limit remains low.

The pursuit model shares sightings among two or three scripted ground pursuers. It approximates flanking, projectile lead, gunfire, lightning and zone pressure. It omits a full 15-enemy squad, opponent progression, every other weapon combination and a full match economy. Scenarios begin during pursuit and cannot establish how often this failure occurred in official matches.

## Compatibility and checks

* All 52 unit and integration tests passed.
* On 12 held-out cases each, the candidate reached the target circle, collected the pickup and captured the uncontested drop in 12/12, matching the baseline on all three. Mean zone damage on the zone trials stayed at zero.
* On 12 single-opponent cases, both versions survived all 12 and eliminated nine opponents. Mean damage taken rose from 836.2 to 851.2 HP.
* The official replay checker accepted 300/300 responses on the host, 300/300 in the linux/amd64 Docker image under the competition flags and 300/300 in the additionally constrained container. No stale responses, wrong ticks, invalid lines or misses. Maximum latencies were 1.0, 1.7 and 1.6 ms respectively.
* On 800 dense generated observations, host latency including JSON parsing and encoding was 2.85 ms median, 6.92 ms p99 and 23.04 ms maximum. Zero decisions exceeded 50 ms. These are observed timings for the tested inputs.
* Docker validation verified the read-only root and arena, isolated network, tmpfs, unprivileged UID, native library and map loading. The rootless daemon exposed 2 CPU equivalents, 8 GiB memory and unrestricted swap/PID cgroups. The additional run enforced one-core affinity, a 512 MiB address-space limit and a 128-process resource limit. Peak bot RSS was 49.1 MiB. Exact scorer cgroup enforcement remains unverified.

The raw paired trials and execution logs are in validation/results/retreat-v2. To reproduce, build geometry.so in both project directories as described in README.md, then run the following from the candidate directory. Supply the path to a clean eecc4f9 checkout as BASELINE.

```sh
for bot in "$BASELINE" .; do
  for approach in mixed long; do
    python3 validation/squad_trials.py --kit mechfight-kit --bot-dir "$bot" --split holdout --cases 20 --approach "$approach"
  done
done
```
