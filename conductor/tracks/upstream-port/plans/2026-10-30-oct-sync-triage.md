# Oct 2026 Upstream Sync — Triage & Port Roadmap

**Status:** IN-PROGRESS — Wave 1 COMPLETED 2026-10-30 (merge 57536204; record commits/42-57536204-oct-sync-wave1.md)
**Started:** 2026-10-30
**Range:** 98 upstream/master commits, `0a10ad1e` (2026-06-13, #554) .. `53ddb024` (2026-10-26, #750)

Untracked since the 2026-06-10 sync. The fork's 3-layer architecture means no git merge/cherry-pick: every
item is a semantic port. Triage verdicts below were made by checking each upstream diff against
`software/src/squid/`. "Bug present" means the defect was confirmed in our code.

**Totals (tracking YAML):** 27 ported (Wave 1) · 12 skipped · 27 deferred · 32 pending (Waves 2–4)

`d25a1b73` and `b40b187b` (test follow-ups) were ported alongside #674 / #621.

Each suite below gets its own `plans/YYYY-MM-DD-<slug>.md` + `commits/NN-<hash>-<slug>.md` when started,
per the upstream-check skill.

---

## Wave 1 — Silent-corruption & robustness fixes — ✅ COMPLETED

Bugs confirmed present in our fork; low design risk; do first.

### 1a `camera-trigger-freshness`
- [x] `f8fe36d9` - camera: don't reuse a pre-trigger frame (#599) — `drivers/cameras/base.py:428` fast path ignores `_last_trigger_timestamp`; laser-AF verify reads stale frames. Check Andor's `send_trigger` override sets the timestamp.
- [x] `e34dec3d` - snapshot cached frame in reuse guard (#603)

### 1b `robustness-quickfixes`
- [x] `e86a608f` - ToupCam all-zero frames, read-buffer realloc race (#585) — `toupcam.py` reads buffer twice, reassigns unlocked
- [x] `f3bca2cb` - LAPE int16 overflow on 8-bit (#679) — `core/utils/hardware_utils.py:54`, `image_processing.py:253`
- [x] `5be72178` - stage timeouts `min`→`max` (`cephla.py:23`), focus-map double move (`focus_map.py:461`), MCU timeout messages (#618). **Re-verify homing / long moves / SQUID_TEST_SPEEDUP.**
- [x] `0f789a45` - tolerate corrupt `last_coords.txt`; atomic write (#621) (+ `b40b187b` test tweak)
- [x] `f453dc18` - save/restore XY on stage without Z (#692)
- [x] `b8f508c4` - Celesta HTTP timeout (#643)
- [x] `1f4130f2` - laser-engine serial `write_timeout` (#576)
- [x] `74824168` - Preferences reads ini inline comments wrongly and writes them back (#665) — `ui/widgets/config.py:973`
- [x] `2a550c86` (partial) - laser AF honours `.ini` crop sizes (#674); keep simulation fallbacks
- [x] `72bdd2fc` (startup part) - guard `emission_filter_wheel.home()` in `prepare_for_use`

### 1c `small-correctness-batch`
- [x] `0a10ad1e` - populate `region_shapes` for flexible/single/template regions (#554)
- [x] `ee7897c9` - skip focus-map interpolation for single-FOV snap (#577)
- [x] `df83fe32` - 1536-well row sort AA–AF after Z (#600)
- [x] `b43ddbe3` - emission filter wheel index: we hardcode `{1: …}` in **4** places (upstream fixed 2): `live_controller.py:306`, `multi_point_worker.py:2216`, `acquisition_service.py:279`, `application.py:1313`
- [x] `39b091e4` - live FPS interval from trigger start (#716)
- [x] `06a91af4` - hide Continuous trigger mode unless ENABLE_RECORDING (#561)
- [x] `2092c2ee` - X-Light: skip emission command if already in position (#602)
- [x] `53ddb024` (partial) - shared `QSpacerItem` in ~10 layouts in `flexible_multipoint.py` → teardown double-free (#750)
- [x] `30a193e7` (partial) - idempotent `Microscope.close()` (#604)
- [x] `85917dc7` (generic parts) - shared software-line intensity update; idempotent light-source close (#709)
- [x] `26a80322` (partial) - Windows FTDI latency warning helper + Optospin call (#726)

### 1d `fw-build-hygiene` (config-only; needs one hardware build check)
- [x] `ff7aad6a` - pin FastLED 3.10.3 / PacketSerial 1.4.0 (#725) — our `^3.6.0` floats to 3.10.5+, which logs onto the binary protocol port
- [x] `9d8a5f56` - `-D FASTLED_LOG_VERBOSITY=0` (#660)

---

## Wave 2 — Acquisition performance & behavior (M each, ~4–5 days)

### 2a `saving-format-tiff`
- [ ] `aa9107d9` - file-format menu default bug (`config.py:344,1321`), TIFF compression, frozen `SaveSettings` snapshot on Job (#652)

### 2b `acq-overhead-abort`
- [ ] `55236d92` (2 of 3 parts) - remove `_temporary_get_an_image_hack` (~1.2 s + stray trigger per acquisition), skip unchanged mode sets (~22 ms/image) (#712). Clear the cache on every channel/mode event (AF, z-offset, orchestrator).
- [ ] `70f2afdd` (generic parts) - prompt abort mid z-stack, return Z by steps taken (via ZStackExecutor); fix NL5 double `start_acquisition` (#711). RcmScanTrigger stall recovery → defer (AION/NL5 only).
- [ ] `1adae748` - single-pass copy+flip in `rotate_and_flip_image` (all cameras) + Tucsen view (#721). Port pixel-equivalence test.

### 2c `live-snap-and-motion-hold`
- [ ] `752c9bb8` + `f9305f9f` - Snap button on main live panel (LiveController command + StreamHandler force-display)
- [ ] `7385a179` - hold live triggers while MCU busy / stage moving; multipoint start survives busy MCU (#639). Host-side guard is our only fix for the MCU wedge.

### 2d `coordinates-z-csv`
- [ ] `856bc0ee` - save/load Z in coordinate CSVs; **fixes focus-map Z leaking into GUI ScanCoordinates** via shallow copy (`multi_point_controller.py:952`)

### 2e UI items
- [ ] `c8f69125` - napari multichannel viewer responsive during large z-stacks (#713)
- [ ] `9a8a7afd` - line profiler: multiple lines, H/V/Full/Fill; fixes centerline/rounding/off-image accuracy bugs (#732)
- [ ] `8779ced6` - reorderable channel sequence in multipoint widgets; reuse `ChannelOrderWidget` (#557)
- [ ] `edc13253` - illumination config edits without restart (stale `_illumination_config` snapshot, Cancel leaks edits); per-channel `max_output` (#610)

---

## Wave 3 — Larger features needing design (L, ~1–2 weeks)

### 3a `channel-config-persistence` → `laser-af-offsets`
- [ ] `24276973` - persist configurator-added channels (#589) — do first (shared seeding helper)
- [ ] `6919470e` - per-channel z-offset for laser AF (#551)
- [ ] `52c6f586` - default per-channel z-offset OFF (#598) — **behavior change: we apply offsets unconditionally today**
- [ ] `ecd84920` - log actual z after offset move (#573)
- [ ] `e1ad4cc6` - hide z-offset UI without laser AF (#686)
- [ ] `d5fc5abd` - per-region laser-AF offset (#562)
- Design: must coexist with continuous focus lock + AF executor; new EventBus commands instead of widget → `measure_displacement()`.

### 3b `camera-trigger-lock-sensor-mode`
- [ ] `875eda71` - `_trigger_lock` in ABC + Hamamatsu sensor mode (#605). Structural lock refactor separate from behavior. Decision: drop triggers (upstream behavior).
- [ ] `56db6965` - persist sensor mode (#612)
- [ ] `8bf3c7d0` - Hamamatsu frame ids from DCAM framestamp (#661)

### 3c `live-viewer-overexposure-alignment`
- [ ] `46a139b9` - overexposure mask + alignment/auto-align on pyqtgraph viewer; optional napari-live removal (#627). Split into a–d; auto-align publishes stage commands.

### 3e `plate-geometry` (approved 2026-10-30; own plan required)
- [ ] `18fff8f2` - one well-to-stage transform, geometry/placement split, holder-rotation calibration (#611). Reconcile with our wellplate calibration (plans/2026-02-07).
- [ ] `1b1e9f26` - disable sample formats from dropdown (#736)

### 3d `unified-mosaic-followups`
- [ ] `dd0c4cd2` - keep Full View tiles across magnification changes (#566). Unblocked now that step 2b wiring is done (808dec3b).

---

## Wave 4 — Hardware-specific (hardware confirmed in use)

- **Dragonfly:** `432772be`, `594440a3` (generic part: confocal wheels in channel configurator)
- **X-Light V3:** `5d992336` non-iris half (iris → existing confocal-iris deferral)
- **Tucsen / Aries:** `5442ac0c` (stale binning in readout calc — bug present), `1a54d891`
- **ToupCam refresh:** `4b610458`, `074d0f91` (SDK 60.x binaries)

---

## Deferred

| Group | Commits | Reason |
|---|---|---|
| Firmware 1.5–1.8 | `da109c5a`, `17dc0444`, `12ebfebd`, `334487d9`, `37d2e005`, `e6d84e29`, `5faaad47`, `90cc5dd0`, `72bdd2fc` (rest), `e3d502a4`, `ad1edd66` | No PlatformIO/Teensy here; no filter wheel in use (consistent with 2026-06-09 firmware deferral) |
| **Firmware joystick-panel safety** | `7c27f8e2`, `670b80ea`, bounds fix in `ad1edd66` | **Bugs present in our firmware** (Z jump on panel replug; wheel input stalls commanded moves). First item for the next hardware session. |
| PI V-308 / Z-lift | `d83cdabf`, `1fdaab6c`, `9878d13a`, `f207b049`, `fd4586de`, `8a3e458c`, `a93850e2` | Hardware not owned |
| Laser engine v2 | `67746338`, `85bef316` | New hardware; `LightSource.use()` hold design worth revisiting |
| Objective turret | `a518249e`, `8c62827a`, `091bf4e8`, `a77cbac3` | Turret not in use (2026-10-30). Note: our existing turret port has the startup Z-restore deadlock and homes at focus — revisit if a turret is fitted. |
| PyQt6 opt-in | `1c13072e` | Need to remove direct PyQt5 imports in 9 modules first |
| Slack watchdog | `7dfd75ca` | Consistent with earlier Slack deferral |
| VersaLase / RcmScanTrigger | `85917dc7` driver, NL5 parts of `70f2afdd`/`55236d92` | NL5/AION not in use (2026-10-30) |

## Skipped

| Commit | Reason |
|---|---|
| `0306f194` | already-fixed (`_acquisition_in_progress` guard) |
| `780d80e3` | superseded (tab change publishes event) |
| `4baf7135`, `1cceeacc`, `a7cc89be`, `c04e5f0d` | superseded by our ExperimentProtocol V2 / orchestrator fluidics |
| `1f04ceed` | already implemented (`acquisition_order`); optional coordinates.csv follow-up |
| `e64c2ee2` | not-applicable (single Utils menu already) |
| `c05bef3a`, `49d1ef74`, `81b6c5aa`, `200f9a26` | test/CI-only for upstream code paths we don't share |

## Decisions (2026-10-30)

1. **Hardware in use:** Dragonfly, X-Light V3, Tucsen/Aries, ToupCam, Hamamatsu. **Not needed:** objective turret, NL5/AION → turret suite and NL5/AION-specific parts deferred.
2. Per-channel z-offsets become opt-in, default OFF — **approved**.
3. Wellplate geometry refactor `18fff8f2` (+ `1b1e9f26`) — **go**; moved to Wave 3 (3e), needs its own plan.
4. Camera trigger contention — **drop triggers** (upstream behavior) when the trigger lock is held.
