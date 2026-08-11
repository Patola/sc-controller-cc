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

[0.6.0.8]: https://github.com/Patola/sc-controller-cc/releases/tag/v0.6.0.8
