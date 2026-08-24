# Homelab efficiency assessment

## Scope and evidence

This report uses repository configuration, live Talos/Kubernetes/Prometheus telemetry, supplied Synology and UPS screenshots, and first-party product or service documentation. It does not replace per-device wall measurements. Talos identifies the compute hardware as one EliteDesk 800 G2 SFF and two EliteDesk 800 G1 SFF systems. The rest of the hardware is a Synology DS1621+, three Mellanox ConnectX-3 10 GbE adapters using SFP+ DACs, a TP-Link TL-ST1008F or close equivalent, a UniFi US-8-60W, and a UniFi Flex Mini. `hp3` is reported as unstable. Configured workloads include Rook storage, media applications, databases, monitoring, home automation, public web applications, and USB-attached workloads. Exact per-device wall power and the TP-Link hardware revision remain unknown.

Numbers below are either **known facts**, **estimates**, or **model-dependent**. No savings claim is exact until measured at the wall.

## Observed live-cluster baseline on 2026-08-22

Talos, Kubernetes, and Prometheus supplied the measurements below. They are point-in-time or seven-day software telemetry, not wall-power measurements.

- Talos identifies the machines as full **small-form-factor desktops**, not EliteDesk Minis: `hp1` is an HP EliteDesk 800 G2 SFF with an i7-6700, while `hp2` and `hp3` are EliteDesk 800 G1 SFF systems with an i7-4790 and i7-4770 respectively. Each CPU has 4 physical cores and 8 threads. All three 10 GbE adapters are Mellanox ConnectX-3 cards using the `mlx4_core` driver.
- `hp1` has 40 GiB installed across all four DIMM slots. `hp2` and `hp3` each have 32 GiB across all four slots. Kubernetes exposes 40, 32, and 32 GiB respectively after platform reservations.
- The cluster currently runs 190 pods: 70 on `hp1`, 68 on `hp2`, and 52 on `hp3`. A `kubectl top nodes` sample showed 1.34, 0.98, and 1.34 logical CPU cores in use and 15.5, 14.7, and 12.0 GiB of memory. Seven-day mean active CPU was 1.54, 1.22, and 1.58 logical cores; five-minute peaks were 4.00, 3.15, and 7.58. Current aggregate demand fits two machines much more comfortably than one.
- Container working-set memory was approximately 14.6 GiB for application pods, 10.3 GiB for `kube-system`, 6.25 GiB for Rook-Ceph, and 3.1 GiB for monitoring. Rook and Kubernetes platform overhead are therefore major consolidation targets. They matter more than moving a few tiny web applications.
- Rook is healthy now, but its design assumes the three hosts: three monitors, three OSDs, host failure domains, and block-pool replication size 3. It stores 164 GiB of logical data as 426 GiB of raw usage across three 238 GiB NVMe OSDs. There are 109 `ceph-block` claims. Removing `hp3` therefore requires a storage migration or a deliberate pool redesign before powering it off.
- `hp3` had been up for about 74 hours, compared with about 331 hours for `hp1` and `hp2`, and its boot-time metric changed during the retained 30-day data. This agrees with the reported instability. Its current CPU package temperature was around 50 C, below `hp2` at roughly 57 C, so the current snapshot does not point to overheating as the cause.
- The three 10 GbE interfaces averaged only 0.7 to 6.4 MiB/s of combined send and receive traffic over seven days. Five-minute peaks reached 155 MiB/s on `hp1`, so 1 GbE would extend large transfers but would probably handle steady traffic. This supports testing 1 GbE for ordinary cluster traffic while retaining one direct 10 GbE path for NAS transfers.
- The UPS powers the homelab and desktop, but not the printers. Its energy log therefore cannot isolate homelab consumption. The recent rise from 210.4 W to 311.8 W coincides with increased work-from-home use and overnight desktop LLM workloads, so this report does not use that trend to size homelab changes.
- Prometheus shows cluster CPU demand remained essentially flat while UPS consumption rose, which is consistent with the desktop causing most of the increase. Per-device measurements or a temporary desktop shutdown baseline are required to determine homelab watts and cost.
- A representative set of public or easily moved services (`sparkleandspin`, Ghost, WordPress, Umami, Harvco, Gatus, Smokeping, CyberChef, and IT-Tools) used about 1.6 GiB of container memory and 0.10 logical CPU cores on average. Moving only these services will not materially cool the office while all three HP systems remain powered.
- The Synology screenshots show four 9.1 TiB HGST HUH721010ALE604 HDDs in bays 2-5, a 476.9 GiB Kingston SKC400S37512G SATA SSD in bay 6, an empty bay 1, and two healthy but unallocated 238.3 GiB WD PC SN810 NVMe drives. Volume 1 on Storage Pool 1 uses 19.5 TB with 6.7 TB free. Volume 2 on the single SATA SSD uses 68.5 GB with 378.8 GB free.
- A detailed RBD usage scan found 174.5 GiB in live `csi-vol` images, but only 123.0 GiB belongs to currently bound PVCs. Of that bound data, 62.6 GiB is in claims named as caches and 60.4 GiB is non-cache application data. A detached 51.6 GiB image carries metadata for an old `volsync-plex-src` snapshot and should be reviewed before deletion. This makes a 238.3 GiB mirrored NVMe target practical if cache claims and retained snapshots are handled deliberately.

The central constraint is storage, not compute. Current CPU demand supports two physical hosts. One existing host would be tight on memory and peak CPU until Rook, duplicate control-plane processes, and some optional applications are removed.

## What is known from primary sources

- The Synology [DS1621+ product specification](https://global.download.synology.com/download/Document/Hardware/ProductSpec/DiskStation/21-year/DS1621%2B/enu/Product_Spec_DS1621%2B_enu.pdf) lists an AMD Ryzen V1500B, four 1 GbE ports, PCIe expansion, 51.22 W access power, and 25.27 W during HDD hibernation. Those power figures use six specified 1 TB hard drives and exclude the exact installed disks and 10 GbE card, so they are product-test facts rather than this installation's consumption. The same specification lists 174.77 BTU/h during access.
- The [UniFi Flex Mini technical specification](https://techspecs.ui.com/unifi/switching/usw-flex-mini) identifies five 1 GbE ports, USB-C 5 V power or PoE, 2.5 W maximum power, and 8.5 BTU/h heat dissipation. It is not a 10 GbE switch. Replacing a larger always-on edge segment with it can reduce device power only if the other switch can provide required uplinks and PoE; it cannot replace the 10 GbE path.
- The noisy switch is a [UniFi US-8-60W](https://techspecs.ui.com/unifi/switching/us-8-60w). Ubiquiti specifies fanless cooling, 12 W maximum consumption excluding PoE output, and a 48 W PoE budget. No endpoint needs PoE, although the Flex Mini may currently take PoE on its uplink. The high-pitched noise therefore cannot be a fan; the switch or its external power supply is producing it.
- Talos identifies all three adapters as Mellanox MT27500 ConnectX-3 cards using `mlx4_core`. The [NVIDIA ConnectX-3 documentation](https://docs.nvidia.com/networking/display/connectx3pro) covers this generation. Their exact firmware, DAC length, and measured power remain unknown.
- The likely [TP-Link TL-ST1008F specification](https://service.tp-link.com.cn/download/pdf/1584.pdf) describes eight SFP+ ports, IEEE 802.3z and 802.3ae support, fanless operation, and a 12 VDC/2 A supply. The 24 W adapter capacity is not measured switch consumption. IEEE 802.3z support makes true 1 GbE SFP copper modules preferable to hotter 10GBASE-T SFP+ modules for the router uplink, desktop, UPS card, and Flex Mini.
- 10GBASE-T and SFP+ DAC are different physical layers. The [SFF-8024 specification](https://members.snia.org/document/dl/2591) defines SFP identifiers and capabilities, while the [IEEE 802.3 standard](https://standards.ieee.org/ieee/802.3/10748/) defines Ethernet PHYs. In practical terms, 10GBASE-T generally needs more PHY power and produces more heat than a short passive DAC, but the adapter and switch implementation dominate. Measure the actual pair rather than applying a generic watt figure.
- HP's [Elite Mini business desktop specifications](https://support.hp.com/us-en/document/ish_3915183-3915220-16) and [HP Computer Setup (BIOS) documentation](https://support.hp.com/us-en/document/ish_3915183-3915220-16) describe model-dependent BIOS power controls such as C-state/idle behavior, wake timers, and scheduled power options. Exact menu names and availability depend on the EliteDesk generation and BIOS. Talos can use Linux CPU idle states, but the BIOS and NIC link state determine whether those states save meaningful power.

## Heat and electricity model

Every watt consumed at the wall becomes approximately one watt of heat in the room. For a steady load `P` watts, monthly energy is:

```text
kWh/month = P × 24 × days_in_month ÷ 1000
monthly cost = kWh/month × tariff ($/kWh)
```

For a 30-day comparison, **estimate**: 1 W continuous = 0.72 kWh/month. At an unknown tariff `T`, that costs `0.72 × T` dollars/month. A measured 25 W reduction is therefore 18 kWh/month, but its dollar value depends on the tariff. Cooling savings are not separately added: lower IT watts reduce room heat directly and may reduce air-conditioning energy, but that multiplier is site-specific.

Do not add nameplate maximums for a total. Measure each AC input, including power supplies, switch PoE output, and UPS losses where applicable.

## Options

### 1. Keep three nodes and reduce power first

- Measure idle and representative busy power for each node. Enable supported HP CPU idle/power controls, disable unused onboard devices, and use NIC power management only where it does not break 10 GbE stability. Apply workload requests/limits and schedule nonessential CI, media indexing, timelapse processing, and scans. Keep three nodes if Rook replication, maintenance availability, or failure tolerance requires them.
- Investigate `hp3` before using it as a reliability anchor. A failing node can waste energy through retries, crashes, and repeated recovery. If it is not reliable, remove it from storage and scheduling according to the cluster's documented operational process; this report does not change cluster resources.
- Tradeoff: lowest migration risk and preserves capacity, but three platform baselines and three NICs remain. Sleep or power-off schedules are unsuitable for workloads needing continuous quorum, storage replication, Frigate capture, or ingress.

### 2. Consolidate to two nodes

- Two nodes can host stateless services and the Synology-backed workloads, but Rook's replication and failure behavior must be checked first. The repository has a three-replica Dragonfly cluster and Rook storage; reducing nodes can make anti-affinity, quorum, and maintenance behavior worse. A two-node design may require changing storage architecture, not simply draining one node.
- Expected direction: remove one entire node's measured idle watts and its 10 GbE port, while increasing load and possibly fan speed on the survivors. Savings are **estimate only** until per-node readings and workload headroom are known.
- Tradeoff: meaningful heat reduction and simpler hardware, with less failure tolerance and less room for upgrades.

### 3. One node plus Synology

- Put public/stateless applications, GitOps controllers, monitoring, and light databases on one EliteDesk Mini; retain large files, backups, and selected media on the DS1621+. Keep Frigate recording, download workloads, and USB devices local if their latency, bandwidth, or device access makes cloud or NAS placement unsuitable.
- This is viable only after testing memory, CPU, storage IOPS, and recovery time. Rook's distributed storage is not automatically a fit for a one-node cluster; a single-node storage design changes failure semantics. The NAS is not a replacement for an independent backup.
- Tradeoff: largest likely platform power reduction, but a single-node failure becomes a broad outage. Keep the second node powered off but ready if the service set permits it.

### 4. Replace or simplify network equipment

- First identify the TP-Link 10 GbE model, the UniFi 8-port PoE model, power supplies, fan curves, and PoE devices. A 10 GbE switch remains necessary if all three nodes and the NAS need simultaneous 10 GbE. A fanless switch can address the reported whine and heat, but port count, VLAN features, jumbo-frame behavior, DAC compatibility, and management support must match.
- Use the Flex Mini only for low-bandwidth 1 GbE edge devices. Its official 2.5 W maximum is a useful upper-bound product figure, but PoE conversion losses and its upstream switch port still draw power. Consolidating unused 1 GbE links onto it can let a larger access switch be removed, if PoE is not needed.
- A short DAC between compatible SFP+ ports is usually preferable to 10GBASE-T for heat and power, but verify Mellanox firmware, switch support, cable length, and link stability. Do not replace stable links solely from generic transceiver claims.

### 5. Move selected public/stateless services to Azure

- Azure VM hosting can suit small public web frontends, API gateways, CI jobs, and intermittently used development services. The repository's `sparkleandspin` frontend/backend, `hi-events`, `ccattendance`, `ghost`, `umami`, and similar stateless services are candidates after dependency and data-flow review. Keep Frigate camera ingestion, media libraries, SABnzbd traffic, Rook, and bulk backups local: their data movement and persistent storage are likely to dominate economics and latency.
- Azure's [Linux VM pricing page](https://azure.microsoft.com/en-us/pricing/details/virtual-machines/linux/) says managed disks are charged separately, standard egress charges apply, and a VM must be **Stopped (Deallocated)** to stop compute billing. A running VM plus disk, public IP, monitoring, snapshots, and outbound traffic can exceed a USD 50 monthly credit even when the VM's advertised compute price appears small.
- Use the [Azure pricing calculator](https://azure.microsoft.com/en-us/pricing/calculator/) with Australia East or another region actually available to the subscription. Microsoft lists Australia and New Zealand currencies on its pricing material, but currency conversion and tax are not fixed USD-credit equivalents. Region availability and quota must be checked in the target subscription.
- Prefer a single small Linux VM or scheduled jobs over multiple always-on managed services. Azure Container Apps, Functions, and Static Web Apps may fit bursty stateless workloads, but each has separate request, execution, storage, networking, and egress meters. Use first-party [Container Apps pricing](https://azure.microsoft.com/en-us/pricing/details/container-apps/), [Functions pricing](https://azure.microsoft.com/en-us/pricing/details/functions/), and [Static Web Apps pricing](https://azure.microsoft.com/en-us/pricing/details/app-service/static/) before committing.
- Avoid Azure Database for PostgreSQL/MySQL as a default migration for small homelab databases: compute, storage, backup, and network charges are separate. Keep databases local unless managed availability is worth the credit and the calculator shows headroom. See [Azure Database for PostgreSQL pricing](https://azure.microsoft.com/en-us/pricing/details/postgresql/flexible-server/) and [Azure bandwidth pricing](https://azure.microsoft.com/en-us/pricing/details/bandwidth/).

## What the USD 50 Visual Studio credit can cover

The [Visual Studio subscriptions page](https://visualstudio.microsoft.com/vs/pricing/?tab=paid-subscriptions) currently describes Professional standard as including a USD 50 Azure credit per month. Verify the user's actual subscription because the credit amount depends on subscription type. Microsoft states in [Azure subscription and credit documentation](https://learn.microsoft.com/en-us/azure/devtest/offer/quickstart-create-subscription) that monthly credits are for eligible development/test use, expire at the end of each monthly period, and cannot be carried forward; confirm the current offer terms in the subscriber portal. The Azure offer can be disabled or incur charges if spending limits, subscription status, or terms change.

A credit can plausibly cover one small always-on Linux VM plus modest managed disk and low traffic, or intermittent compute, **only after calculator validation**. It is unlikely to cover multiple always-on VMs, a managed database, substantial disk snapshots, monitoring, public IPs, and sustained outbound media traffic together. Egress is charged by Azure's bandwidth meters, and internet egress from public web/media services can consume the credit quickly. Never place the primary media library or backup corpus in Azure merely because compute appears within USD 50.

## Practical target designs

### Best balance: two HP hosts, Synology storage, optional quorum VM

1. Move the 68.5 GB from the single SATA SSD volume to the 6.7 TB available on HDD Storage Pool 1 and verify its backup.
2. Create a Btrfs RAID 1 pool from the two 238.3 GiB NVMe drives. Synology officially requires verified SSDs for M.2 storage pools, but the maintained third-party [`Synology_M2_volume`](https://github.com/007revad/Synology_M2_volume) project lists the DS1621+ as confirmed working and creates RAID 1 pools on DSM 7. Its documentation warns that a DSM update can make an unsupported pool appear missing until `Synology_HDD_db` is run. Keep the scripts and recovery procedure on HDD Storage Pool 1 and off the NAS, and test the recovery before depending on the pool.
3. Put bound application state on the NVMe pool through NFS or iSCSI. The currently bound data is about 123 GiB, or about 52 percent of a 238 GiB mirror. Put regenerable cache claims on node-local storage or HDD Pool 1, and put snapshots and backups on HDD Pool 1 plus the existing independent backup destination.
4. Remove Rook only after restoring representative applications from the new storage and backup path.
5. Move the Coral from `hp3` to `hp1` or `hp2`, then retire `hp3`. Keep `hp1` and `hp2` as Kubernetes hosts. This retains 72 GiB of installed memory and removes one old desktop, one ConnectX-3 link, one NVMe OSD, and a third copy of every node-level daemon.
6. If control-plane fault tolerance matters, the DS1621+ officially supports [Virtual Machine Manager](https://www.synology.com/en-us/dsm/packages/Virtualization). A small control-plane-only Talos VM can retain three etcd voters without a third physical HP system. The [etcd FAQ](https://etcd.io/docs/v3.7/faq/) explains that three members tolerate one failure while two members tolerate none. Test NAS reboot and recovery behavior because the NAS would host storage and one control-plane member.

This option provides the largest likely heat reduction without forcing every workload onto one aging four-core system.

### Maximum reduction: one host, Synology, Flex Mini

Use `hp1` as the sole compute host because it is newer and already has 40 GiB. Replace its two 4 GiB DIMMs if testing shows that 40 GiB lacks headroom. Remove Rook and use NAS or local storage. Keep `hp2` powered off as a recoverable cold spare.

If only the compute host and NAS need 10 GbE, test a direct ConnectX-3-to-NAS DAC with static addresses. Put management and ordinary LAN traffic on the Flex Mini. A successful direct link can remove the TP-Link switch as well as two unused Mellanox cards. This design has the lowest heat and least network hardware, but host maintenance causes an outage and the NAS becomes central to most stateful services.

### Lowest-risk immediate change: remove the US-8-60W

The TL-ST1008F has exactly enough ports for the current topology: four existing DACs for `hp1`, `hp2`, `hp3`, and the Synology, plus four 1 GbE copper SFP modules for the router uplink, desktop, UPS management card, and Flex Mini. The printers remain on the Flex Mini. If the Flex Mini currently takes PoE from the US-8-60W, power it through its supported 5 V USB-C input before moving the uplink.

This lets the 10 GbE interfaces carry both the 10.0.16.0/24 LAN and the 172.20.0.0/24 Ceph subnet on the same unmanaged Layer 2 switch. Talos currently places the default route and VIP on the onboard 1 GbE interfaces, so this requires a clean interface-address migration. Do not leave the same node address active on both interfaces during the cutover.

Removing the US-8-60W saves at most its specified 12 W plus power-supply losses, offset by the extra SFP modules and possible Flex Mini USB-C supply. The certain benefits are removing the whine, one hot enclosure, one power supply, and four redundant 1 GbE node/NAS links.

### Heat-first alternative: move the equipment

Moving the NAS, HP systems, and switches to a ventilated utility space, garage, or network cupboard removes their heat and noise from the office even if electricity use stays unchanged. Check ambient temperature, humidity, dust, cable length, UPS access, and fire safety first. Fiber or ordinary Ethernet is more practical than long DACs between rooms.

### Azure: use the credit for bursty dev/test work, not bulk migration

The official Azure retail API currently lists a Linux `B2als v2` in New Zealand North at [USD 0.0499/hour](https://prices.azure.com/api/retail/prices?%24filter=serviceName%20eq%20%27Virtual%20Machines%27%20and%20armRegionName%20eq%20%27newzealandnorth%27%20and%20skuName%20eq%20%27B2als%20v2%27), or about USD 36.43 for 730 hours. It has [2 vCPUs and 4 GiB RAM](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/basv2-series). A 32 GiB E4 Standard SSD is currently [USD 3.4272/month](https://prices.azure.com/api/retail/prices?%24filter=serviceName%20eq%20%27Storage%27%20and%20armRegionName%20eq%20%27newzealandnorth%27%20and%20skuName%20eq%20%27E4%20LRS%27), before operations, backup, public IPv4, monitoring, and egress. An 8 GiB `B2as v2` is USD 0.0998/hour, about USD 72.85/month before storage, so it exceeds the USD 50 credit.

The measured public-service set might fit a 4 GiB VM only after including the guest OS and databases in a real trial. It still removes only about 0.10 average CPU cores locally. Azure becomes an energy measure only when the move lets a physical node or switch stay off.

Better uses of the credit:

- Azure Container Apps jobs for intermittent CI, scheduled processing, preview environments, and development services. The [consumption plan](https://azure.microsoft.com/en-us/pricing/details/container-apps/) scales to zero and includes monthly grants of 180,000 vCPU-seconds, 360,000 GiB-seconds, and two million requests.
- Static Web Apps or static storage hosting for truly static frontends such as CyberChef, IT-Tools, and any buildable static site.
- One small dev/test VM for public project services whose total persistent data and egress remain small.

Do not move Frigate, Home Assistant, Zigbee2MQTT, CUPS, Plex, Immich media, download clients, Ceph data, or NAS backups to Azure for this goal. They depend on local devices or move too much data. Also verify that each workload complies with the Visual Studio benefit's dev/test-only terms.

## Measurement plan

1. Record exact model numbers, installed drives, RAM, NICs, switch power supplies, PoE loads, and Azure subscription offer. Record ambient temperature and whether the UPS reading is input or output.
2. Use a calibrated wall-plug meter on each node, NAS, TP-Link switch, UniFi PoE switch, Flex Mini supply, and UPS input. Log at least 24 hours idle and a representative busy interval; record average, minimum, maximum, and watts during media/transcode, storage scrub, backup, and CI activity.
3. Perform a per-device shutdown test during a maintenance window: remove one device from service, power it off at the wall, and verify that storage, ingress, DNS, camera capture, backups, and monitoring still meet the intended service level. Restore it and repeat for each node and switch. Do not power off a storage node without checking Rook health and recovery state.
4. Test network alternatives one change at a time. Compare the present 10 GbE DAC path with the candidate switch or PHY, checking link errors, throughput, temperatures, fan noise, and wall watts.
5. Record the tariff in NZD/kWh, fixed daily charges, and any controlled-load rates. Calculate monthly kWh and cost from measured averages; keep heat as watts and optionally estimate cooling impact separately.
6. For Azure, export a workload inventory: CPU-hours, memory-hours, persistent GiB-month, backup GiB-month, requests, outbound GiB, and region. Enter these into the official calculator and set a budget alert below the credit limit. Test deallocation and data restore before moving production traffic.

## Recommended order

1. Consolidate the network onto the TL-ST1008F and Flex Mini using true 1 GbE copper SFP modules for the four copper clients. Supply the Flex Mini by USB-C if its current uplink provides PoE. Then remove the whining US-8-60W.
2. Move the 68.5 GB from SATA SSD Pool 2 onto HDD Pool 1 and verify its backup.
3. Create a two-drive RAID 1 Btrfs pool on the existing NVMe drives with `Synology_M2_volume`, document the DSM-update recovery procedure, and test it before migrating Kubernetes data.
4. Migrate the roughly 123 GiB of bound Ceph data while placing regenerable caches and snapshots on appropriate cheaper storage. Confirm whether the detached 51.6 GiB Volsync Plex image is still needed.
5. Remove Ceph, move the Coral, drain `hp3`, and operate two physical hosts. Add a control-plane-only Talos VM on the Synology only if the tested availability benefit justifies the dependency.
6. Measure homelab-only power after shutting down or separately metering the desktop.
7. If further heat reduction matters more than host availability, trial all workloads on `hp1` with memory headroom and keep `hp2` powered off as a cold spare.
8. Use Azure credit for scale-to-zero development jobs, previews, CI, or static sites. Move always-on applications only when doing so permits local hardware to remain off.

## Facts requiring exact model numbers or measurements

- The HP models, CPUs, and installed RAM are now known; wall draw, power-supply efficiency, BIOS idle settings, and the practical memory-upgrade limit still require inspection or measurement.
- The NICs are ConnectX-3 cards; firmware, port mode, DAC length, and switch transceiver implementation remain unknown.
- The likely TP-Link model is TL-ST1008F; verify its label, revision, existing copper module type, switch wall draw, and added-module temperatures.
- The NAS drive inventory and volume usage are known; Storage Pool 1 RAID mode, NAS 10 GbE card, measured wall draw, and the purpose of the 68.5 GB on Pool 2 remain unknown.
- The UPS tariff is configured as NZD 0.25/kWh, but the UPS also powers the desktop. Homelab-only wall power, cost, and seasonal cooling load remain unknown.
- Longer-horizon application peaks, Kubernetes requests, backup volume, public request rate, internet egress, and the exact Azure subscription eligibility.
