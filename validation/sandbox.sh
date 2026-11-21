#!/usr/bin/env bash
# Run from any directory. Arguments are the project and extracted official kit.
set -euo pipefail
bot=$(realpath "${1:?Usage: sandbox.sh PROJECT STARTER_KIT}")
kit=$(realpath "${2:?Usage: sandbox.sh PROJECT STARTER_KIT}")
tag=${BOT_IMAGE:-mech-royale-local:validated}
map_staging=$(mktemp -d)
trap 'rm -rf -- "$map_staging"' EXIT
# A private archive extraction can leave map files unreadable to container uid 65534.
chmod 755 "$map_staging"
install -d -m 755 "$map_staging/v2"
install -m 444 "$kit/arena/v2/world.json" "$kit/arena/v2/terrain.i16" "$map_staging/v2/"
docker build --platform linux/amd64 -t "$tag" "$bot"
flags=(--rm -i --network none --cpus 1 --memory 512m --read-only
       --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$map_staging:/arena:ro")
checker=(python3 "$kit/check/check.py" --map-dir /arena -- docker run)
"${checker[@]}" "${flags[@]}" "$tag"

# Report the limits actually visible inside Docker. Rootless daemons may accept
# resource flags without creating a cgroup, so the second run pins the process
# to one available CPU and enforces address-space and process rlimits as well.
docker run "${flags[@]}" --entrypoint python3 "$tag" -c '
import json, os
from pathlib import Path
from ctypes import CDLL
from arena import Arena
CDLL("/bot/geometry.so")
assert os.getuid() == 65534 and os.getgid() == 65534
assert os.statvfs("/").f_flag & os.ST_RDONLY
assert os.statvfs("/arena").f_flag & os.ST_RDONLY
assert not (os.statvfs("/tmp").f_flag & os.ST_RDONLY)
tmp = os.statvfs("/tmp")
assert tmp.f_blocks * tmp.f_frsize <= 64 * 1024**2
assert set(os.listdir("/sys/class/net")) == {"lo"}
assert Path("/arena/v2/world.json").stat().st_size > 0
with open("/arena/v2/terrain.i16", "rb") as f:
    assert f.read(2)
arena = Arena("/arena", json.loads(Path("/bot/defaults.json").read_text()))
assert arena.handle, arena.error
arena.close()
assert int(next(line.split()[1] for line in Path("/proc/self/status").read_text().splitlines() if line.startswith("CapEff:")), 16) == 0
for name in ("cpu.max", "memory.max", "memory.swap.max", "pids.max"):
    path = Path("/sys/fs/cgroup") / name
    print(name, path.read_text().strip() if path.is_file() else "unavailable")
'
guard='
import os, resource, sys
core = min(os.sched_getaffinity(0))
os.sched_setaffinity(0, {core})
for which, cap in ((resource.RLIMIT_AS, 512 * 1024**2), (resource.RLIMIT_NPROC, 128)):
    resource.setrlimit(which, (cap, cap))
assert os.sched_getaffinity(0) == {core}
assert resource.getrlimit(resource.RLIMIT_AS) == (512 * 1024**2,) * 2
assert resource.getrlimit(resource.RLIMIT_NPROC) == (128, 128)
pid = os.fork()
if pid == 0:
    os.execv(sys.executable, [sys.executable, "-u", "/bot/main.py"])
_, status, usage = os.wait4(pid, 0)
print(f"Bot peak resident memory {usage.ru_maxrss / 1024:.1f} MiB", file=sys.stderr)
sys.exit(os.waitstatus_to_exitcode(status))
'
"${checker[@]}" "${flags[@]}" --pids-limit 128 --memory-swap 512m \
    --cap-drop ALL --security-opt no-new-privileges \
    --entrypoint python3 "$tag" -c "$guard"
