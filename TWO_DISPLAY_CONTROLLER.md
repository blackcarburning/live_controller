# Experimental Windows two-display controller

`live_controller_two_display.py` is a separate version of the Windows controller.
The original `live_controller.py` remains unchanged. Do not run both versions at
the same time: they would compete for global hotkeys, MIDI and serial devices.

## Start the new version

Use the same Python environment and dependencies as the original. From
`C:\PythonDev`, after closing the other controller when it is safe to do so:

```powershell
& "C:/Path/To/Python313/python.exe" -B "C:/PythonDev/live_controller_two_display.py"
```

Replace the example Python path with the interpreter used for the original
controller. No launcher or original source file needs to be replaced.

## Five zones, two independent outputs

Keep Windows in **extended desktop**, not duplicate/mirror mode. HDMI and DP are
logical output roles, not automatically detected physical connector types.
The default targets are the first and second extended displays (mpv indices 1
and 2); check the displayed monitor names/indices before using an audience screen.
The operator/primary screen is not an automatic fallback. Missing, changed or
duplicate selections disable the affected video output and show a warning;
audio and MIDI continue. Native display mapping still requires a real-machine
check.

In the existing multi-zone editor:

- Keep the five existing zones and their global **Enable** controls.
- Route each zone to **HDMI**, **DP**, **Both**, or neither. Legacy zones default
  to HDMI without changing their enabled/disabled state.
- Source crop is shared. A zone routed to Both uses the same source content on
  each monitor.
- Choose **Editing output: HDMI / DP** to change that output's zone scale, border
  and Y offset, composite crop/scale, stitch direction, output canvas and timing.
  These destination settings are independent.
- Unrouted/disabled zones close up in existing stitch order. This is not a new
  free-X/Y placement system.
- Separate **HDMI Still Preview** and **DP Still Preview** tabs show the two
  composites from the captured frame. These are still previews, not live video.
  External previews are silent and belong to the selected output.
- An output with no assigned enabled zones must not expose the full raw source.

The original Composite and Final Preview controls are retained. Switching the
editing output changes their destination context; it does not create a sixth
source zone or change another output's scale.

## Audio and MIDI take priority

There is one headless audible/timeline master and at most two silent video
followers. The original master audio release and MIDI scheduling remain the
authority. Video readiness, corrections and cleanup run outside the MIDI timing
path; a failed video follower must not stop or retime the master.

This is **not frame-locked multi-monitor rendering**. Additional decoding and
rendering can increase machine load, and mixed refresh rates/driver behavior
remain relevant. Video may lag, skip or seek to catch up. Audio/MIDI performance
under real show load still needs a controlled live qualification.

Stopping or closing retains ownership of audio/MIDI worker threads until they
actually finish. If a worker is still stopping, new playback/calibration is
blocked and closing waits rather than destroying a running thread. Do not start
the other controller version while shutdown is still pending.

- **Video offset** is an integer number of source frames. Positive means video
  later than audio; negative means video earlier. Out-of-range positions hold
  the first/last usable frame.
- **Drift limit** is an integer frame threshold for follower correction, not
  seconds. It must never alter audio delay, audio position, speed or MIDI timing.
- Source FPS, including fractional rates, is used for conversion at the video
  IPC boundary. If FPS is unavailable, the explicitly reported fallback is
  25 FPS. For variable-frame-rate media this is nominal-frame timing, not a
  guarantee of exact frame-index correspondence.

## Separate saved state

The new version writes `two_display_*` state, including configuration, session,
zoom settings, BPM/track-name stores, captured frame and its own setlist folder.
Where no new state exists, supported legacy files are read as a migration
source only. Automatic writes and guarded exports must not overwrite the old
controller's state. Shared source crops/global enables/routes and per-output
settings are saved together in the new schema; import/export uses the same
migration rules.

To return to the original controller, close this version safely and run the
unchanged `live_controller.py`. This is a separate launch choice, not a rollback
of the original script.

## Verification boundaries

See [the offline test instructions](checks/two_display/TESTING.md). Tests extract
selected definitions rather than import or launch the hardware-connected app.
Windows checks include real offscreen Qt widgets and a dedicated test of actual
Win32 named pipes owned entirely by the test process. These do **not** start mpv,
play media or open real MIDI/serial devices.

The completed Windows offline results and exact tested source hashes are in the
[verification record](checks/two_display/RELEASE_VERIFICATION.md).

Offline results do not prove installed mpv option support, physical HDMI/DP
selection, live lip sync or audio/MIDI timing under load. Only the named selected
regression suites are covered; this is not a full repository test-suite pass.
