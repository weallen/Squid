# Oct 2026 Sync — Wave 2 (acquisition performance & behavior)

**Our Commit:** `d2f8bafc` (merge of `oct-sync-w2a`..`oct-sync-w2d`)
**Date:** 2026-10-30
**Status:** PORTED (some partial — see notes)
**Plan:** `plans/2026-10-30-oct-sync-triage.md` (Wave 2)

## Upstream Commits Ported

| Upstream | Our commit | Title |
|---|---|---|
| `aa9107d9` | `8bb0fb3a` | fix(saving): file-format menu default, TIFF compression, SaveSettings snapshot (aa9107d9) |
| `edc13253` | `5244bdf4` | test(illumination): pin the config-change mode-controller refresh as in-memory only |
| `edc13253` | `3124967f` | fix(illumination): clamp acquisition intensity to channel max output (edc13253 follow-up) |
| `edc13253` | `d1942b30` | fix(illumination): apply config edits without restart; per-channel max output cap (edc13253) |
| `8779ced6` | `6404d6b2` | feat(acquisition): reorderable channel acquisition sequence in multipoint widgets (8779ced6) |
| `1adae748` | `080b5758` | perf(camera): single-pass copy+flip per frame, zero-copy Tucsen read (1adae748) |
| `70f2afdd` | `5e15c0ca` | fix(acquisition): stop a z-stack at once on abort, Z back to stack start (70f2afdd) |
| `7385a179` | `09f1687d` | fix(live): hold live triggers while the MCU is busy; acquisition start survives a busy MCU (7385a179) |
| `9a8a7afd` | `eebc491e` | feat(ui): line profiler with multiple lines, H/V/Full/Fill FOV; fix profile accuracy (9a8a7afd) |
| `55236d92` | `d23c9048` | perf(acquisition): no test frame for disk estimate, skip unchanged mode sets (55236d92) |
| `752c9bb8` | `04c076bd` | feat(live): Snap button for single-frame capture on the main live panel (752c9bb8, f9305f9f) |
| `f9305f9f` | `04c076bd` | feat(live): Snap button for single-frame capture on the main live panel (752c9bb8, f9305f9f) |
| `856bc0ee` | `12a1b7eb` | fix(multipoint): save/load Z in coordinate CSVs; stop focus-map Z leaking into GUI coordinates (856bc0ee) |
| `c8f69125` | `d7445b37` | fix(napari): keep multichannel viewer responsive during large z-stacks (c8f69125) |

Extra (not upstream): `24f166af` fix(prefs): `_get_changes()` referenced nonexistent `sim_microcontroller_checkbox`
(every Preferences Save raised AttributeError; fixes 7 `TestChangeDetection` failures on master).
Follow-ups on w2d: `3124967f` max-output clamp in the acquisition path, `5244bdf4` refresh-cost test.

## User-visible behavior changes

- **Abort is immediate** mid z-stack / channel loop (was: after the full level/loop). A position cut short is
  marked FAILED in the checkpoint so resume re-images it.
- **Acquisition start** no longer grabs a test frame (~1.2 s faster); unchanged channel modes are not re-applied.
- **Live (hardware trigger)**: triggers are skipped while the MCU is busy (stage moving). Acquisition start
  waits up to 15 s for an idle MCU, else fails cleanly.
- **Snap** button on the live panel; live button reads "Live"/"Stop".
- **Coordinate CSVs** save/load `z (mm)`; Load button toggles Load/Clear.
- **Channel order** in flexible/wellplate/fluidics multipoint = the order channels are checked (drag to reorder);
  persisted in `cache/channel_sequence.yaml`. Only the active tab publishes channel selections.
- **TIFF compression level** in Preferences (INDIVIDUAL_IMAGES / MULTI_PAGE_TIFF); file-format default fixed;
  format/compression changes after startup now take effect (SaveSettings snapshot per acquisition).
- **Illumination**: config edits apply without restart; Cancel discards edits; per-channel `max_output` caps
  the live slider and the power set during acquisitions.

## Architecture Adaptations / Deviations

- `55236d92`: mode-skip cache invalidated on position change, AF/laser-AF, focus-lock verify, per-channel
  z-offset, and EventBus config/mode/illumination/trigger/objective events (our worker applies modes via
  services, so upstream's LiveController check doesn't apply).
- `70f2afdd`: Z return reuses `ZStackExecutor.return_to_start()` (absolute home) — `steps_taken` logged only.
  NL5 double `start_acquisition()` removed from the worker. RcmScanTrigger etc. not ported (NL5/AION unused).
- `aa9107d9`: also fixed the worker's import-time `FILE_SAVING_OPTION` staleness. `ZARR_USE_6D_FOV_DIMENSION`
  has the same staleness (left as upstream did).
- `752c9bb8`: Snap runs on a worker thread off the EventBus; `StreamHandler.force_next_display()` one-shot.
  New events are plain (non-frozen) dataclasses — the `Event` base is not frozen.
- `7385a179`: `PeripheralService.is_mcu_busy()` (lock-free). Busy-check → trigger is not atomic (same gap as upstream).
- `856bc0ee`: `ScanPositionInformation` deep copy; `update_fov_z_level` removed; CSV helpers in
  `ui/widgets/acquisition/coordinates_csv.py`.
- `8779ced6`: reuses `ChannelOrderWidget(ordered_selection=True)`; drag to reorder, no ▲/▼ buttons.
- `c8f69125`: driven by `AcquisitionStateChanged` (no `napari_layers_init` signal in arch_v2).
- `edc13253`: `ChannelConfigService._illumination_config` is now a live property; `MicroscopeModeChanged`
  carries `max_illumination_intensity`. `AcquisitionService` is never constructed in the app (dead path).

## Tests

~200 new tests (mode cache 15, prompt abort 42, rotate/flip equivalence, Tucsen view, TIFF compression 26,
preferences file format 11, snap 18, motion hold 14, coordinates CSV 25, channel order 21, napari multichannel 8,
line profiler 30, illumination config/cap ~33).

Full unit suite per file (`--timeout=10 --timeout-method=thread`) branch vs master: **identical failure sets** (no new failures).

## Pre-existing issues observed (not fixed)

- `tests/unit/control/widgets/test_event_bus_widgets.py` aborts the Python process.
- `test_handle_z_offset_moves_relative`, `test_acquire_at_position_pauses_focus_lock_before_preparing_z_stack`,
  `test_gen_focus_map_invalid_bounds_publishes_failure` (calls nonexistent `set_reflection_af_flag`),
  `test_workflow_flexible_snap_acquisition` ("delta_z_um must be > 0"), `test_drain_processes_pending_events`,
  5 orchestrator workflow integration tests.
- `tests/unit/control/test_stubs.py` hardcodes `/tmp/` (blocked by sandbox).
- `test_image_display_line_profiler.py` crashed pytest once in 6 runs (cause unknown).

## Audit

- [x] Logic matches upstream (deviations listed above)
- [x] arch_v2 patterns followed (widgets publish commands; services/controllers own logic)
- [x] Tests added
- [ ] Hardware verification: Tucsen zero-copy view, hardware-trigger live hold, X-Light/confocal with mode skip
