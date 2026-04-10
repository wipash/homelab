# Home Assistant Unresponsiveness Investigation

**Date:** 2026-04-10 (started), updated 2026-04-11
**Status:** Awaiting debug logging data from next morning spike

## Symptom

Home Assistant becomes unresponsive every morning for approximately 60-90 minutes. Response times spike to 5000ms+ and health checks fail. Occurs daily around 06:00 NZST (18:00 UTC), visible in Gatus response time graphs going back multiple days. Other services on the same node (Plex, zigbee2mqtt) also experience outages due to compounding I/O storms.

## Outage History (from Gatus)

| Date | HA Outage Window (NZST) | Duration | Other Services Affected |
|------|------------------------|----------|------------------------|
| Apr 8 | 03:35-07:10 | ~3.5 hours | — |
| Apr 9 | 06:25-07:25 | ~55 min | — |
| Apr 10 | 06:00-07:05 | ~65 min | Plex (2x), zigbee2mqtt |
| Apr 11 | ~06:00 (expected) | — | zigbee2mqtt (33 restarts in 9d), Plex (13 restarts in 47h) |

## Root Cause Analysis

### Two separate issues compounding

#### 1. Daily HA CPU Spike (~06:00 NZST) — UNDER INVESTIGATION

HA's CPU ramps from ~20m to ~950m over 45 minutes, then stays pegged for 60-90 minutes. Fine-grained (1-minute) CPU data shows this is NOT a sudden spike at 06:00 but a **gradual ramp starting at ~05:15 NZST** with a clear 5-minute oscillation pattern:

```
04:12 NZST: purge fires (nightly task)
04:30 NZST:  31m  (tiny bump, purge finishes quickly)
04:35-05:10: 10-15m  (completely idle — purge is done)
05:15 NZST:  26m  ← first bump
05:27 NZST:  59m  ← growing
05:39 NZST:  49m  ← growing
05:48 NZST:  92m  ← accelerating
05:54 NZST: 207m  ← steep ramp
05:59 NZST: 450m
06:00 NZST: 920m  ← pegged for ~90 min
07:25 NZST:  21m  ← drops back to normal
```

**Key findings:**
- The 5-minute oscillation matches the `StatisticsTask` that fires every 5 minutes in HA's recorder
- **Not the auto_purge**: The nightly purge at 04:12 finishes quickly (visible as a tiny bump at 04:30) with 1+ hour of idle CPU before the ramp starts
- **Not database I/O**: PostgreSQL backend metrics are flat during the spike. This is CPU-bound Python work inside HA
- **No scheduled task at 06:00**: HA source code confirms the only daily task is the purge at 04:12. No task runs at 06:00
- **Duration correlates with DB size**: Apr 8 (DB was 1.4GB): 3.5 hours. Apr 10 (after cleanup): 65 min
- **Logs show no trigger**: Nothing logged at INFO level when the ramp starts. The recorder thread doesn't log at INFO level during statistics compilation

**What it's NOT:**
- Not the `auto_purge` (that fires at 04:12 and finishes by 04:30)
- Not a database-heavy operation (PG metrics flat)
- Not a CronJob or Kubernetes scheduled task
- Not a specific HA automation (checked logs — only a manual button press at 05:57)
- Not any obvious integration based on log analysis
- Not Ceph scrubbing (Ceph health OK, scrub schedule doesn't align)

**Current theory:** The 5-minute `StatisticsTask` is getting progressively more expensive during the early morning hours. Possibly related to `CompileMissingStatisticsTask` (runs at startup and re-queues itself until complete), or an interaction between the purge and subsequent statistics compilation passes.

**Next step:** Debug logging enabled on `homeassistant.components.recorder.statistics` and `homeassistant.components.recorder.core`. Check Loki after the next morning spike (2026-04-12 ~06:30 NZST) with:
```
{app="home-assistant"} |~ "recorder|statistics|purge"
```

#### 2. Hourly Volsync I/O Storms on hp1 — FIXED

All 28 Volsync backup jobs were scheduled at `0 * * * *` (top of every hour, simultaneously). This caused:
- **650% iowait** on hp1 (load average spiking to 30 on an 8-core machine)
- All I/O on hp1 stalled for 10-25 minutes every hour
- Services on hp1 (zigbee2mqtt, Plex, prowlarr) repeatedly killed by liveness probes
- NodeSystemSaturation alerts firing hourly

When the hourly I/O storm overlapped with the daily HA CPU spike, the combined load caused the worst outages (health check failures, MQTT timeouts, websocket backlogs).

**Fix:** Staggered all backup schedules across the hour (2-3 min apart). Large volumes (Plex 100Gi, Frigate, Audiobookshelf) moved to every 6 hours. At most 1-2 backups overlap at any time now.

**Note:** The stagger commit (`d9975fff3`) was initially blocked from deploying by a YAML syntax error in `hi-events/ks.yaml` (an uncommented line in a commented-out YAML document). This was fixed on 2026-04-11 and confirmed deployed. The last unstaggered run was at 09:00 NZST Apr 11.

### Contributing Factors

#### hp1 Overload

hp1 was running an outsized share of workloads including HA, Plex, Mosquitto, zigbee2mqtt, the CNPG operator, and ~28 Volsync backup pods simultaneously. Combined with PCIe bus errors on hp1's NVMe drive, this made hp1 the most failure-prone node.

**Fixes applied:**
- Volsync backups staggered (see above)
- CNPG postgres17 instances pinned to hp2/hp3 (done Apr 10)
- hi-events pinned to hp2/hp3 (done Apr 10)
- HA node affinity restriction removed — no longer excluded from hp3 (done Apr 11, now running on hp2)
- Plex hp3 exclusion removed (done Apr 11, Coral/Frigate anti-affinity remains)

#### CNPG Replica Instability on hp1

The postgres17 replica (postgres17-3) on hp1 suffered constant connectivity failures: 150+ timeout errors over 3 days, WAL receiver timeouts, and a failover on Apr 7. The high rollback rate on the HA database (19%) was likely caused by transactions timing out during I/O stalls.

**Fix:** postgres17 instances pinned to hp2/hp3 with pod anti-affinity. Replica migrated to hp3.

#### hp1 PCIe Bus Errors

hp1's NVMe drive (WD PC SN810) generates recurring PCIe correctable errors (Data Link Layer Timeouts, Physical Layer RxErr) every 30-90 minutes. SMART data shows the drive is healthy. May resolve now that I/O storms are eliminated.

**Status:** Monitoring. Physical inspection (reseat NVMe) recommended if errors persist.

#### Recorder Configuration Issues (Fixed)

- `auto_purge_time: "02:00:00"` was not a valid recorder option, causing the recorder integration to fail entirely on startup. **Removed.**
- `purge_keep_days` reduced from 30 to 10 — daily purge processes much less data
- Entity exclusions active — ~2M rows from noisy sensors purged, won't be re-added

## Current Node Placement

| Service | Node | Constraint |
|---------|------|-----------|
| CUPS | hp1 | Pinned (printer hardware) |
| Frigate | hp3 | Requires Coral TPU |
| Plex | hp1/hp2 | Excluded from hp3 (Coral anti-affinity with Frigate) |
| Home Assistant | any (currently hp2) | No constraint |
| postgres17 | hp2 (primary), hp3 (replica) | Pinned to hp2/hp3 |
| hi-events | hp2/hp3 | Pinned away from hp1 |

## Remaining Actions

- [ ] **Analyze debug logging after 2026-04-12 morning spike** — determine what recorder task causes the gradual CPU ramp from 05:15 NZST
- [ ] **Monitor first staggered Volsync run** — verify hp1 load stays under 5 at the top of the next hour
- [ ] **Monitor hp1 PCIe errors** — if they persist after I/O reduction, physically reseat the NVMe
- [ ] **Consider staggering r2 (daily remote) backups** — all 27 still fire simultaneously at `30 0 * * *` (12:30 NZST)
- [ ] **Consider adding more noisy entities to the exclude list** — run periodically:
  ```sql
  SELECT sm.entity_id, count(s.*) as state_count
  FROM states_meta sm
  JOIN states s ON s.metadata_id = sm.metadata_id
  GROUP BY sm.entity_id
  ORDER BY state_count DESC LIMIT 25;
  ```
