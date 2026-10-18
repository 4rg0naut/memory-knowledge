---
origin: demo/sources/harbor-fleet.md
format: mem-wiki@2
retrieved_at: 2026-10-18
content_hash: 112156d743ac9a56b79b34dba2562856bcfa9ac0b7b80849540e02e4b6ccb374
kind: file
producer: demo-harness
session_id: demo-publish
---
# Harbor Robotics fleet briefing (2026-10-02)

Harbor Robotics builds warehouse automation robots; headquarters in Rotterdam, founded 2021.

The R200 warehouse robot runs on the Nimbus-9 SoC. The R200 unified memory is 128 GB across all production SKUs, per the hardware sheet.

Fleet firmware status_of: 4.2.1 as of the October rollout.

The depot sync job has a known gotcha: rsync without --delete leaves orphaned files from withdrawn rosters alive on the mirror.

The R200 pick arm sustains 310 picks per hour under the standard bin mix.

