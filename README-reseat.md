# ProForge 5 standalone reseat overlay

Built for Maeve's `config-20261023-131306` upload. This is configuration code, not a hardware-tested firmware release. Keep the bed clear and supervise initial cold tests. Dock and carriage switches cannot prove that a tool is mechanically secure.

## Install and remove

Restore the PH2–PH5 offsets in `variables.cfg` first (the earlier recovered block). Keep your existing pickup/dock coordinates. Copy `reseat.cfg` into the config folder and add `[include reseat.cfg]` **after every other include/override and before the SAVE_CONFIG block** in `printer.cfg`. Restart Klipper while idle. Do not include the old `proforge_reseat.cfg` together with this overlay.

The file intentionally redeclares existing macro sections; Klipper merges config sections, with later options winning. Do not add `rename_existing` to the redeclared tool macros. Existing PAUSE/RESUME/CANCEL aliases supplied by the base config are retained.

To remove: comment out `[include reseat.cfg]` and RESTART. No settings are written to `variables.cfg`; no existing macro files are edited. Back up `printer.cfg` and any existing `reseat.cfg` before installation.

## Settings

All recovery settings are at the top of `reseat.cfg` in `_RS`:

- Safe machine X = 0; all five reseat endpoints = -47.
- Approach at 150 mm/s; last 5 mm at 2 mm/s, in 0.5 mm increments, checking switches between increments. Stop pushing as soon as the dock reads pressed. Verify again after withdrawing.
- Push acceleration = 100 mm/s²; original acceleration is restored after each push increment.
- Two reseat attempts per dock, one XY-home pickup retry per tool, one redocking retry per tool, and a bounded overall operation.
- Servo angles 52/100, 1.1-second wait only when commanded PWM changes or a forced relock is requested. Software cannot measure the actual servo angle.
- Uses the current `variables.cfg` pickup/dock Y positions. PH3 pickup Y=211 and dock Y=213; PH4 pickup Y=313 and dock Y=315 in the supplied upload.

## Behavior

`SELECT_PH1`–`SELECT_PH5`, `T0`–`T4` (existing aliases), `DOCK`, calibration pickup/dock helpers, and prime pickup helpers use the same transaction logic. Calibration helper overrides remove the stock double pickup.

A mounted tool is identified from a single open dock, or from the last successfully verified pickup. The active extruder is never used as proof of physical tool identity. If multiple docks are open immediately after startup and the mounted tool is unknown, it stops without guessing. Manual changes to tools can invalidate remembered identity: cancel any print and use `PF_CLEAR` after inspection.

For an empty carriage with loose docks, borrow from a pressed dock, verify attachment and withdrawal, reseat the loose docks, return the borrowed tool, verify the dock states, then complete the original request. `PF_RESEAT` leaves an originally mounted tool mounted; with an initially empty carriage it finishes empty with all docks pressed.

XY must already be homed before entry. The only automatic XY homing retry occurs after a failed pickup when the carriage reads empty, the requested tool still reads docked, and the carriage has withdrawn to safe X. A dropped/ambiguous tool prevents that retry. During a print, lift 2 mm before travel and return to the original print coordinates after successful selection/reseating. Insufficient Z clearance stops before travel. Normal tool XYZ offsets and the live offset adjustment are preserved; calibration pickup uses zero tool offsets intentionally.

No delayed callback initiates recovery or motion. Original delayed postchecks are disabled by overrides. The top-level transaction executes a bounded series of separate stage macros, so each stage reads fresh status after the previous motion and settling wait. This also avoids recursive macro execution, which Klipper prohibits.

## Failure and pause

A failure sets a persistent runtime lock, pauses a running print without parking, retains heater targets and motors, and raises an error to abort the caller. The virtual-SD error handler is overridden so this particular error does not invoke the stock automatic cancel. Other virtual-SD errors still cancel normally. Klipper may display the print status as **error**, with the pause flag set and file retained.

After inspecting/correcting the mechanics:

1. `PF_RESEAT_STATUS` reports state.
2. `PF_RETRY` retries the saved operation with fresh sensor checks and bounded attempts; it does **not** resume printing.
3. After a successful retry, `RESUME` is allowed.

Klipper virtual SD retains the failed file line; RESUME executes that line again. A simple `Tn`/`SELECT_PHn` is checked as already selected after successful recovery. If the failed line was a larger startup/calibration macro, inspect its effects before resuming: the entire macro may run again.

Failures before saving a transaction (e.g. missing offsets or unhomed XY) cannot use PF_RETRY. Correct the setup and cancel/restart as appropriate. `PF_CLEAR` abandons runtime state only when no print is running or paused. It does not move the carriage.

Paused idle timeouts rearm instead of disabling heat/motors. Cancel explicitly turns heaters off, cancels the file, and avoids automatic docking; motors remain enabled until normal idle timeout. End print docks and verifies before shutting down motors. A failed end-print dock retains the lock and motors.

## Validation and limits

`test_reseat.py` compiles templates and interprets stage execution against the uploaded base macros. It models fresh per-macro snapshots, physical/gcode coordinate conversion, saved state, offsets, and Klipper's prohibition on recursive macro calls. Cases cover five pickups, normal switching, already-selected, mounted reseating, empty-carriage borrowing for selection/DOCK/PF_RESEAT, pickup homing retry, docking retry, failures, explicit retry, print return with live Z adjustment, calibration single pickup, and missing offsets.

This is a simulation. It does not emulate MCU scheduling, real sensor debounce/false positives, physical latching, bed-mesh transforms, extrusion dynamics, or collision geometry. A successful simulated test is not proof that unattended recovery is safe. Test cold with a clear bed before attempting it during a print.
