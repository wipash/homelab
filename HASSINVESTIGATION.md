# Home Assistant Unresponsiveness Investigation

**Date:** 2026-04-10
**Status:** In progress — awaiting confirmation after config fix

## Symptom

Home Assistant becomes unresponsive every morning for approximately 1 hour. Response times spike to 5000ms+ and health checks fail. Occurs daily around 06:30 NZST (18:30 UTC), visible in Gatus response time graphs going back multiple days.

## Investigation Findings

### Database State

- **Database:** `home_assistant` on CNPG cluster `postgres17` (PostgreSQL 17.4)
- **Total DB size:** 1,372 MB
- **`states` table:** 853 MB / 3.1M rows (plus ~445 MB in indexes)
- **`statistics_short_term` table:** 242 MB / 1.4M rows
- **`statistics` table:** 200 MB
- **Dead tuple levels:** Normal (autovacuum working correctly)
- **Rollback rate:** 77,207 rollbacks vs 337,653 commits (19% — very high)

### Top entities by row count in `states`

Many of the heaviest hitters are entities the user has already added to the recorder exclude list, but the exclusion had not yet taken effect:

| Entity | Rows |
|--------|------|
| sensor.energy_usage_without_heatpump | 371,690 |
| sensor.shellyproem50_*_power | 300,051 |
| sensor.shellyproem50_*_apparent_power | 300,029 |
| sensor.ups_power | 213,565 |
| sensor.system_power_vdc | 162,034 |
| sensor.system_power_battery | 132,593 |
| sensor.shellyproem50_*_power_factor | 112,368 |

These ~2M rows from excluded entities are now being purged.

### Daily CPU Spike Pattern (Apr 9 data)

```
18:30 UTC (06:30 NZST):  0.894 cores  — ramp up
18:35 UTC:                1.503 cores
18:40-19:25 UTC:          ~1.95 cores  — pegged at container limit for 45 min
19:30 UTC:                0.037 cores  — drops instantly
```

HA hits nearly 2 full CPU cores for 45 minutes, then abruptly finishes. During this period, the frontend is unresponsive (5000ms+ response times, health check failures).

### Rollback Rate Spike Correlates

```
18:00 UTC (06:00 NZST): 0.46 rollbacks/sec
19:00 UTC (07:00 NZST): 2.59 rollbacks/sec  ← peak
20:00 UTC (08:00 NZST): 1.75 rollbacks/sec
```

### Timing Discrepancy

The recorder `auto_purge` runs at **04:12 local time** (16:12 UTC), but the CPU spike occurs at **06:30 NZST** (18:30 UTC) — a 2+ hour gap. This suggests the spike may be caused by HA's **statistics compilation** (which runs on a separate internal schedule) rather than the purge itself, or a combination of both.

### Aggravating Factor: hp1 I/O Storms

HA runs on **hp1**, which experiences hourly I/O storms from Volsync backups (see separate investigation). At 18:05 UTC, the hourly Volsync backup causes 350-450% iowait on hp1. If the HA internal maintenance task coincides with this, the combined load could cause the severe unresponsiveness. This overlap has not been confirmed.

### Config Issue Found

The user's `configuration.yaml` contained `auto_purge_time: "02:00:00"` which is **not a valid recorder option**. This caused the recorder integration to fail entirely on startup, cascading to break `history`, `logbook`, `energy`, and `usage_prediction` — resulting in the frontend stuck on "Loading Data."

## Actions Taken

1. **Removed `auto_purge_time`** from recorder config (invalid option)
2. **Restarted Home Assistant** — recorder now loading correctly
3. **Triggered manual purge** via `recorder.purge` service
4. **Entity exclusions now active** — the noisy sensors listed above will no longer be recorded

## Manual Purge Results

The manual purge with `purge_keep_days: 30` ran at ~200m CPU — significantly less than the 1,950m seen in the daily spikes. This does **not** reproduce the original issue, possibly because:
- No concurrent Volsync I/O storm during the manual purge
- The manual purge service may batch differently than the internal auto process
- The daily spike may be statistics compilation, not the purge itself

## Related Fixes (potential contributing factors)

Multiple infrastructure issues were discovered during this investigation that could be contributing to or compounding the daily HA unresponsiveness. All have been fixed as of 2026-04-11.

### 1. Volsync I/O Storms on hp1

All 29 Volsync backup jobs were scheduled at `0 * * * *` (top of every hour, simultaneously). This caused:
- **600%+ iowait** on hp1 (where HA runs)
- **Load average spikes to 18-19** on an 8-core machine
- All I/O on hp1 would stall for 5-40 minutes depending on the hour

The 18:05 UTC hourly backup directly overlapped with the HA daily spike window (18:30 UTC). The combined I/O contention could explain why HA's internal maintenance pegged at 2 cores — not because the task itself needed 2 cores, but because every DB operation was blocked on I/O.

**Fix:** Staggered all backup schedules across the hour (2-3 min apart). Large volumes (plex 100Gi, frigate, audiobookshelf) moved to every 6 hours. At most 1-2 backups overlap at any time now.

### 2. CNPG Replica Instability on hp1

The postgres17 replica (postgres17-3) was on hp1 and suffered constant connectivity failures:
- **150+ timeout errors** over 3 days between primary (hp2) and replica (hp1)
- WAL receiver timeouts causing replication drops
- A full **failover on Apr 7** (timeline jumped to 15)
- The CNPG operator (also on hp1) had **5 restarts in 4.5 days**

When the replica fell behind or reconnected, WAL replay would generate additional I/O on hp1, compounding the Volsync storms. The high rollback rate on the home_assistant database (19%) may have been caused by transactions timing out during these I/O stalls.

**Fix:** Added node affinity to pin postgres17 instances to hp2/hp3 only, with required pod anti-affinity. Replica migrated to hp3 successfully.

### 3. hp1 PCIe Bus Errors

hp1's NVMe drive (WD PC SN810) was generating recurring PCIe correctable errors:
- **Data Link Layer Timeouts** on PCIe port
- **Physical Layer RxErr** on the NVMe device
- Occurring every 30-90 minutes, unique to hp1 (hp2 and hp3 have zero)

SMART data shows the drive is healthy (0 media errors, 33% used, 100% spare), so these may be a loose connection or thermal issue rather than drive failure. However, during heavy I/O (Volsync storms), these errors could cause brief I/O stalls that inflate load averages and cause health check timeouts.

**Status:** Monitoring. May resolve now that I/O storms are staggered. Physical inspection (reseat NVMe) recommended if errors persist.

### 4. Recorder Configuration

- `purge_keep_days` reduced from 30 to 10 — daily purge now processes ~1/3 the data
- Entity exclusions active — ~2M rows from noisy sensors being purged, won't be re-added
- `auto_purge_time` config error fixed (was preventing recorder from loading entirely)

## Remaining Actions

- [ ] **Monitor auto_purge at 04:12 NZST on 2026-04-11** to see if the daily spike pattern is resolved
- [ ] **Check hp1 load after Volsync stagger takes effect** — verify I/O storms are eliminated
- [ ] **Monitor hp1 PCIe errors** — if they persist after I/O reduction, physically reseat the NVMe
- [ ] **Consider adding more noisy entities to the exclude list** — run this query periodically:
  ```sql
  SELECT sm.entity_id, count(s.*) as state_count
  FROM states_meta sm
  JOIN states s ON s.metadata_id = sm.metadata_id
  GROUP BY sm.entity_id
  ORDER BY state_count DESC LIMIT 25;
  ```
- [ ] **Consider moving HA off hp1** — may no longer be necessary if Volsync stagger resolves the I/O contention, but hp1 remains the busiest node
