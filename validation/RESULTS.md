# Baseline validation and experiments

The user reported an official practice score of 4.27/15 for baseline eecc4f9 after the following local measurements. The updated candidate results are in RETREAT.md. The scorer ranks entries by mean 16 minus placement. The public track describes 48 private practice matches against a cooperative squad, with new-seed free-for-alls in qualifying and the final. The local evaluations exercise particular decisions. They contain neither the squad policy nor a full competitive match.

## Official replay

The stock checker accepted every observation on all three runs. All runs reported zero missed deadlines, wrong ticks, stale responses and bad lines. The hello budget is 20 seconds and the action budget is 50 milliseconds.

| Execution | On time | Ready | p50 | p99 | Maximum |
|---|---:|---:|---:|---:|---:|
| Host Python with freshly compiled geometry | 300/300 | 266 ms | 0.4 ms | 2.5 ms | 4.4 ms |
| Built linux/amd64 Docker image, official flags | 300/300 | 3154 ms | 0.7 ms | 32.7 ms | 35.9 ms |
| Same image with single-core affinity and process resource limits | 300/300 | 2959 ms | 0.7 ms | 4.7 ms | 7.8 ms |

Peak resident memory in the last run was 48.7 MiB. The script checked uid/gid 65534, zero effective capabilities, loopback-only networking, read-only root and map, the 64 MiB tmpfs, and successful native loading of the arena. This host's rootless daemon accepted the competition resource flags while exposing parent cgroups with two CPU equivalents, 8 GiB of memory, and unrestricted PID and swap limits. The additional run enforced one-core affinity plus a 512 MiB address-space limit and a 128-process resource limit and requested the no-swap and PID flags. Exact scorer cgroup and swap enforcement remain unverified. Some evaluations ran concurrently on this host, so the two timings do not measure the effect of affinity.

## Paired movement experiments

On the same 12 development starts per scenario, the preserved integrated version reached the shrinking target circle alive in 11 cases and incurred mean zone damage of 170.4 HP. On one blocked approach the ground planner continued to suggest a route while observed displacement stayed near zero. Short jet recovery raised zone completions to 12 and reduced mean damage to 56.7 HP. Initially a capture-hold flag inhibited recovery on the approach to a drop. Applying the hold only within capture distance raised completed development captures from 10 to 12. Floor weapon pickups stayed at 12 of 12. A regression test checks that a pilot which jets toward a distant drop stops that maneuver inside the ring.

The independent evaluator uses the public campus mesh, bilinear height samples, approximate cylinder motion and collision, observed pickup visibility and nested moving circles. The following separate 12-start sets were held out of development. Each policy faced identical conditions. Half the zone and drop cases required traversing obstructed approaches. Pickups were initially visible. Captures were uncontested.

| Held-out test | Starter | Switchback | Switchback with route search disabled |
|---|---:|---:|---:|
| Reached target circle alive | 11/12 | 12/12 | 10/12 |
| Mean zone damage | 201.7 HP | 0.0 HP | 117.1 HP |
| Collected secondary | 1/12 | 12/12 | 12/12 |
| Captured supply drop | 0/12 | 12/12 | 10/12 |

## Combat and reliability

Across 12 held-out, 24-second campus skirmishes with one scripted gun opponent, Switchback survived 12 and eliminated the opponent in 9. The starter survived 1 and eliminated 0. Mean damage dealt and taken was 1402.5 and 836.2 for Switchback, compared with 810.0 and 1436.2 for the starter. The opponent strafes and pursues. These scenarios omit the other 14 mechs, loot and foliage.

In 256 paired constant-velocity cases per weapon, direct aiming versus velocity lead yielded 161 versus 250 gun hits and 75 versus 256 direct mortar hits. This uses synthetic targets, simulated spread for the gun and an independent collision sampler. The result measures aiming under the specified motion assumption. Opponents changing direction, unseen geometry, or a laser interrupt can materially change a fight.

All 37 unit and integration tests passed. Coverage includes gun and mortar intercepts, laser release, dual-slot firing, projectile avoidance, route recovery, capture, offers, missing observation fields, bridge headroom and courtyard holes. A separate stress run sent 800 dense synthetic observations containing 15 enemy mechs, 12 NPCs, 60 projectiles and 72 loot objects. Host process decision latency including JSON parsing and encoding was 1.82 ms median, 4.91 ms p99 and 25.69 ms maximum, with zero over 50 ms. This measurement excludes stdin/stdout transit.

## Competitive unknowns

The largest uncertainty is sustained multi-enemy pressure after the squad escalates pursuit. A scripted lone opponent and uncontested drops are easier than those situations. Solo duels do not calibrate late-zone placement or how often backtracking to loot attracts another hunter. The graph discretizes the campus and the obstacle probes approximate server edge and overhang handling. The bot models shot-blocking solids and uses server visibility observations for foliage. Upgrade priorities, sound interpretation and the assumed probability of opponents changing course remain heuristic. Official practice is the first opportunity to measure the impact on placement.

[Official competition and scorer description](https://www.joinbuilders.org/buildathon/tracks/builders)
