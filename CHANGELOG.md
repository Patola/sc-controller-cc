# Changelog

This changelog starts at **v0.6.0.8**.

sc-controller-cc began as a fork of [C0rn3j/sc-controller](https://github.com/C0rn3j/sc-controller)
intended to be merged back. While that was the goal there was no reason to keep
a changelog of our own: the changes were a pull request, and upstream's history
was the history that mattered. That pull request was closed, development moved
to this repository's `main` branch, and the two projects have diverged — this
one now carries Steam Controller 2 support, working gyroscope support across
several controllers, and a haptics implementation that upstream does not have.

An independent project needs its own record of what changed and when, so this
file begins with the first release made after that split.

Earlier releases are documented on their
[GitHub release pages](https://github.com/Patola/sc-controller-cc/releases),
from v0.6.0 onward. They are not reproduced here; backfilling notes written for
a different purpose would give a false impression of a continuous record.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow the upstream release they diverged from, with a fourth
component for this fork's own releases.

## [0.6.0.10] - 2026-08-14

A second audit pass from **Sergio Correia** (sergio@correia.cc), who found and
fixed eight further defects; reviewed and regression-tested here. One of his
patches was taken in part, noted in its commit message. Alongside those, a
configuration-loss bug that had been quietly destroying settings.

### Fixed

- **An interrupted save no longer destroys every setting.** The configuration
  was written in place, so anything killing the process mid-write left
  truncated JSON — and the next start "recovered" from that by overwriting the
  file with defaults, keeping no copy. Settings are now written atomically,
  and a configuration that cannot be read is preserved as
  `config.json.broken.N` instead of discarded.
- **Unmapped buttons no longer press the right stick.** On a HID controller
  configured by JSON, every input bit the configuration did not name was
  mapped to bit 31 — which is a real button, `RSTICKPRESS`.
- **The haptic Effect chooser stays available when no controller is
  connected.** Opening a pad's configuration with the controller switched off
  hid the whole Effect row, because "no controller attached" was treated as
  "controller that cannot play effects".
- **Actions replaced over the IPC socket work.** Every button press through a
  replaced action raised TypeError, and a button held while the replacement
  was installed could leave its key stuck down.
- **A stalled controller no longer takes every other one down with it.** The
  USB retry path queued a malformed entry, which crashed the mainloop that
  serves all controllers.
- **Stronger haptic clicks keep their effect.** Scaling a haptic up — the
  firmer click at the edge of a pad — reset it to a plain click and multiplied
  its frequency by a million, so tones and sweeps lost their character.
- **Mode shifts triggered by a stick work.** Conditions on `STICK` read the
  left *pad* instead, and conditions on `RSTICK` never matched anything.
- **The RemotePad driver no longer runs analog handling for button events**, a
  missing `break` between two switch cases.
- Undefined behaviour in the HID decoder's button mapping, a crash in the
  `Replace:`/`Lock:` error path, a race between the daemon's subprocess
  supervisor and shutdown, and a CemuHook call passing one argument too many.
- **A missing kernel header now says so.** Importing without kernel headers
  and without the bundled copy failed with `FileNotFoundError` on a path
  nobody had asked for; it now names what it looked for and how to fix it.
- "Minimize to status icon instead closing" reads "instead of closing".

### Packaging

- `package.nix` builds again: its test gate failed in the Nix sandbox because
  a test re-imported `scc` in a child interpreter that picked up the source
  tree instead of the installed package. Fixed in the test.
- `scripts/nar-hash.py` computes the `fetchFromGitHub` hash for `package.nix`
  on machines without nix, self-testing against a hash nix itself produced.

## [0.6.0.9] - 2026-08-14

### Security

A security audit and fix series contributed by **Sergio Correia**
(sergio@correia.cc), who found and fixed all of the following. Reviewed and
hardware-tested here; two patches were amended (noted in their commit messages),
everything else landed as submitted.

- **Heap overflow in the Steam Controller Bluetooth driver.** Long-packet
  reassembly took a 4-bit packet number straight from the incoming report and
  used it as a write offset into a 256-byte buffer. Packets numbered 14 and 15
  wrote 16 and 34 bytes past the end of it, corrupting adjacent heap data, from
  a value a paired device chooses.
- **The IPC socket was world-accessible.** The daemon set `umask(0)` after
  daemonizing, and applied `chmod 0600` to its control socket only *after* it
  had started accepting connections. Any local user could connect during that
  window -- and the socket accepts commands that run shell actions.
- **Shell injection on daemon restart.** `os.system()` was called with an
  unquoted `sys.argv[0]`.
- **Arbitrary file loading over IPC.** The `Profile:` and `Selected:` commands
  accepted any filesystem path, so a socket client could have an
  attacker-controlled file loaded as a profile or menu -- and profiles may
  contain `shell()` actions. Paths are now confined to the known profile and
  menu directories, and `Replace:` no longer accepts `shell`, `profile`,
  `restart`, `exit` or `turnoff`, including nested inside compound actions.
  (This last filter is defence in depth rather than a boundary: `type()` and
  `button()` must keep working for `Replace:` to have a purpose. The boundary
  is the socket's permissions.)
- **Out-of-bounds reads from malformed HID reports.** The `CLAMP` macro in the
  HID decoder expanded to its own argument -- it never clamped anything -- and
  axis values were read from a report without checking the offset against the
  report's length. Both fixed; the DualShock 4 and DualSense axis parameters
  were recalibrated to suit a `CLAMP` that now works, verified as producing
  bit-identical output across the full input range.
- **Scheduler task ordering.** `Task.__lt__` was missing its `return`, so it
  always compared as false and the priority queue ordered tasks arbitrarily.

### Fixed

- **OSD menu navigation with a stick.** Nudging the stick scrolled far too
  fast, and holding it fully deflected stopped the list dead. Both were the
  same fault: menus feed the stick and the d-pad into one pacer, so the d-pad
  sitting at rest kept cancelling the repeat the stick was driving. Movement
  then happened only on changes — once per controller report — and stopped
  entirely once the stick was held still. Each input is now tracked
  separately and the one deflected furthest wins.
- **The DualSense's sticks rest at centre.** Released sticks sat at roughly
  1500 of 32767 instead of 0, so a menu or a bound mouse drifted on its own.
  The deadzone was too narrow over USB and absent entirely over Bluetooth.
- **A stalled USB control write is reported.** It was discarded silently,
  which made a controller that had stopped accepting commands look like one
  that was simply ignoring the configuration.
- **Gyroscope orientation works on a wired DualSense.** Absolute gyro,
  lean-to-turn and tilt all read the controller's orientation, and over USB
  that orientation was three raw accelerometer components rather than angles:
  the yaw axis answered to roll, pitch ran backwards, and yaw itself could not
  work at all, gravity being no reference for rotation about itself. The wired
  path now integrates the gyro exactly as the Bluetooth path and the
  DualShock 4 already did.
- **Absolute-mode gyro axes on the DualSense point the right way.** Yaw and
  roll came out reversed on both transports, because the driver negated its
  angular rates before the mapper -- which reads them through a sign table
  shared with the DualShock 4. Relative mode was unaffected and looked
  correct, which is what hid this.
- **The d-pad navigates OSD submenus.** In menus like "All profiles" it did
  nothing, while the stick worked there and the d-pad worked in the menu
  above it. A submenu reuses its parent's input lock and so skipped the step
  that enabled d-pad control.

## [0.6.0.8] - 2026-08-11

Two headline areas: the Steam Controller 2's haptics go from a single fixed
click to real continuous rumble plus tones, sweeps and firmware effects; and
the DualShock 4 over Bluetooth becomes properly usable.

### Added

- **HD rumble on the Steam Controller 2.** The driver drives the controller's
  linear-resonant actuators continuously through its own rumble report instead
  of emulating rumble as a train of clicks. A game's heavy and light rumble
  motors reach the left and right actuators separately, so they feel different
  rather than identical.
- **Three haptic effect types on the Steam Controller 2**, choosable per
  binding alongside the existing click: **Tone** (frequency, duration and an
  optional LFO), **Sweep** (a logarithmic glide between two frequencies) and
  **Preset** (the 16 effects baked into the controller's firmware, by name).
- **Touchpad clicks produce a haptic click** on the Steam Controller 2, on
  press and on release, on whichever side was pressed.
- Haptic parameter rows pair a slider with a spin button sharing one value, so
  a range can be explored by feel or a value typed exactly.
- `SCC_HAPTIC_DEBUG=1` logs every haptic report and force-feedback effect as it
  is emitted.

### Changed

- **The application is called "SC Controller CC"** in its window title, About
  dialog, tray tooltip and desktop entry, and has its own application identity
  in AppStream metadata. Installation is unchanged: the commands are still
  `sc-controller` and `scc-daemon`, and configuration stays in `~/.config/scc`.
- **Trackball Mode is greyed out on a right stick**, where a ball provably
  cannot do anything — it models inertia on a surface you lift your finger
  from, and a self-centering stick has no equivalent.
- **The kernel's own input devices are claimed exclusively** for a DualShock 4
  or DualSense connected over Bluetooth. Opening the controller there does not
  displace the kernel driver the way a USB connection does, so its gamepad and
  touchpad nodes stayed live alongside ours.

### Fixed

- **The right stick works as a mouse on the DualShock 4 and DualSense.** Bound
  to Mouse, it drove the pointer in a small circle that sprang back to where it
  started. These controllers deliver their right *stick* in the slot others use
  for a right *touchpad*, and it was being treated as a touchpad — integrating
  position deltas, which cancel exactly on the return journey. Present in every
  release since v0.6.0.4. The same mistake left a right stick bound to a button,
  or used in a ring binding, doing nothing at all.
- **Sensitivity applies with Trackball Mode enabled.** With a ball in the chain
  the sensitivity sliders had no effect at all on a right stick.
- **Bluetooth reconnects work.** Re-pairing left the daemon holding the previous
  connection's file descriptors: the controller was still listed, delivered no
  input, and its touchpad jittered under the kernel's own handling. Three
  independent faults — a callback signature mismatch that could take the whole
  daemon down, a stale bookkeeping entry that permanently suppressed reconnects
  on that Bluetooth handle, and no recovery path when the pad simply vanished.
- **Haptic feedback strength responds to its slider.** The last byte of the
  haptic command is a signed value in decibels, not a 0–255 amplitude; it had
  been sent as an amplitude, so raising the slider did not reliably make
  anything stronger. The slider range is now mapped logarithmically onto the
  gain the firmware accepts.
- **The Strength and Period sliders reach their stated maximum.** Strength
  stopped at 32639 instead of 32767, capping its own range.
- **Saved bindings that use haptic feedback load correctly.** Opening one
  produced an editor with no action in it — output "None", feedback switched
  off, side reset — silently discarding the binding on OK. Effect settings now
  also survive a save-and-reopen, and any other change that rebuilds the editor.
- A **stale compiled extension left in the source tree** shadowed every rebuild,
  so fixes appeared to have no effect. `run.sh` clears them, and the loader
  warns when an older build is preferred over a newer one.
- `pytest` from the repository root no longer fails collection outright when a
  packaging build directory is present.

### Known issues

- **If Steam is running, turn off PlayStation Controller Support.** A DualShock
  4 or DualSense on Bluetooth cannot be claimed exclusively the way a Steam
  Controller can, so Steam and SC Controller CC both drive it at once. The
  symptoms do not look like a conflict: the touchpad glides with an
  acceleration nobody configured, its click gives a mouse button whatever you
  bind, and other bindings work fine. Connecting by USB avoids it. See the
  README.
- Audio streaming to the Steam Controller 2's actuators is not implemented.
- Haptic feedback on button presses is not offered.
- The DualShock 4 has no haptic support at all, despite having motors.
- On the DualShock 4 and DualSense a game's heavy and light rumble arrive
  averaged into one intensity, so they feel the same. Only the Steam Controller
  2 splits them.
- The DualSense's raw gyro scale constant is unverified and its orientation has
  no accelerometer fusion, so pitch and roll drift slowly during sustained
  motion.
- Verified on the Steam Controller 2 and the DualShock 4. The DualSense, Steam
  Controller v1 and Steam Deck have not been re-tested against this release.

[0.6.0.10]: https://github.com/Patola/sc-controller-cc/releases/tag/v0.6.0.10
[0.6.0.9]: https://github.com/Patola/sc-controller-cc/releases/tag/v0.6.0.9
[0.6.0.8]: https://github.com/Patola/sc-controller-cc/releases/tag/v0.6.0.8
