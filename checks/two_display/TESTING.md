# Two-display offline regression checks

This is a **selected** regression suite, not the full repository test suite and
not a live hardware/mpv qualification. It never imports the controller module.
Controller-source execution is explicit AST extraction. The original source and
all existing tests stay unchanged. **Final installed Windows offline gates passed
on 2026-11-09:** 146 selected methods (including 16 real-Qt / four actual-QThread
methods), 74 unchanged Arduino methods, eight native own-pipe cases and 108
selected existing checks. `offline_release_qualified=true`;
`live_hardware_qualified=false`. See [RELEASE_VERIFICATION.md](RELEASE_VERIFICATION.md)
for exact hashes, runtime, receipt hashes, visual evidence and limitations.

## Commands

From the repository root (WSL/Linux):

    python3 -B checks/two_display/run_offline.py --output-dir /tmp/two-display-test-results

Windows reproduction, using the byte-verified source and harness files in an
approved isolated location (the documentation handoff does not write Windows):

    "C:/Python313/python.exe" -B checks/two_display/run_offline.py --require-qt --output-dir <approved-artifact-directory>

Use the actual verified Python path; the example does not assert where Python is
installed. If candidate/baseline are elsewhere, pass --source and --baseline.
Use the tested installed PyQt6; do not install/update packages for this check.
QT_QPA_PLATFORM=offscreen is set before Qt imports inside Python.

## Mandatory boundaries

- The selected AST/Qt suite does not perform full-module import, entry-point
  launch, controller construction, hotkeys, MIDI/serial opens, Windows native
  calls, mpv subprocesses or preview subprocesses. The separate native proof
  intentionally uses real Win32 calls only on its own randomized test pipes.
- Real Qt check extracts the dialog/canvas/helpers plus selected `setup_ui` and
  pure display/status methods into a QWidget SafeHost, never LiveController.
  Poller/player dependencies and saves/activity callbacks are inert. Runtime
  lazy imports allow only already-loaded functools by identity; fonts are
  application-local only. Qt callback exceptions fail qualification. A separate
  class uses only test-owned Event-wait QThreads with actual queued signals and
  QTimer on a QWidget SafeHost; it never constructs production MIDI workers.
- No project runtime data is read to obtain test inputs. Synthetic legacy/new
  data is written solely under temporary isolated fixture paths.
- No commits, branches, pushes, config edits, source edits or Windows writes are
  performed by these checks.
- Receipts log hashes, interpreter/platform, test identities and tracebacks.
  Never include config contents, tokens, API endpoints or hardware identifiers.

## Coverage / release checklist

- Original LF hash 605e78b10af95828d2d09df8eb14aa5c85828be4dd73bc467d96b11ff237c346;
  Windows CRLF hash 56a91df1849bc879584a1ec3cecec2cbdf8222282a21263758cb975c3363e4ee.
- Existing controls, methods, MIDI/hardware helpers and unrelated widgets retained.
- Five shared source-crop zones; enable is global; HDMI/DP/Both routing defaults
  HDMI. An empty routed output must never reveal raw full-frame input.
- Explicit zero migration; idempotence; no input mutation/aliasing; independent
  per-output scale/border/Y offset and composite crop/stretch/canvas/stack;
  JSON round trip and read-only legacy fallback with separate new persistence.
- Duplicate/missing monitor guard; primary authority/follower muted/no MIDI;
  primary video timeline survives no HDMI routing and video-only/no-audio source.
- Integer frame offsets/drift, fractional media FPS and missing-FPS handling;
  conversion only at mpv IPC boundary; correction threshold in frames.
- Bounded IPC, cancellation and cleanup; no follower readiness/IPC/join wait on
  clock hot loop; primary failure cleanup/follower failure nonfatal.
- Pause/seek/EOF/calibration paths and retention of original transport controls.
- Extracted real-widget tests: all five zones, both output editor states and
  preview states, representative render/screenshots and integer-frame widgets.

## Exact audio / native safety gates

`test_two_display_audio_gate.py` pins the complete original timing try and
atomic audible IPC release; only the exact nonblocking attach hooks at the two
existing master launch sites may be removed for comparison. Its ordered fake
MIDI/master-IPC matrix covers 72 combinations plus Stop wait/pre-roll. No
coordinator may own actual audible release or seek/PTS/speed/audio-delay changes.
Both visible outputs are silent followers of one headless audible/timeline master.

`test_two_display_native_protocol.py` uses pure Python Win32 fakes for strict
reply typing, Unicode chunks, cancellation admission races and late-completion
buffer ownership. Parent separately owns `verify_windows_pipe_transport.py`;
that file is unchanged. On the installed final Windows source its separate
proof passed all eight cases, using only its own in-process randomized pipes.
Fake native tests alone are not Windows interoperability proof. Neither result
qualifies real mpv IPC. Seek flags use one `absolute+exact` argument.

## Interpretation

receipt.json records exact source hashes and explicit skipped checks. A
candidate-dependent skip means **not qualified**. Linux missing PyQt is never
a real-widget pass. The historical Linux snapshot below retains that limitation;
the later installed Windows `--require-qt` run executed all 16 Qt methods with
zero skips and completed the offline gate.

The parent completed all 74 unchanged Arduino methods and 108 selected existing
checks against the final installed Windows bytes. The latter are **five selected
unchanged modules: three mirror seams and two actual AST seams**, using the
identical final-byte nested alias fixture; they are not full-suite coverage.
Earlier broad-suite LUFS records (2 failures / 20 errors over 111 cases) are
historical, not a final full-suite rerun or pass claim. Existing assertions
were not weakened. Actual video timing, audio/MIDI performance under load,
physical hotplug and mpv version/option support remain untested live work.

## Arduino compatibility wrapper (unchanged existing tests)

    python3 -B checks/two_display/run_arduino_regressions.py --source <frozen-candidate> --baseline <original> --tests-dir /tmp --logic-only --output-dir /tmp/two-display-test-arduino

Windows all-74 (use the verified interpreter and approved stage/artifact paths):

    <python> -B checks/two_display/run_arduino_regressions.py --source <stage>/live_controller_two_display.py --baseline C:/PythonDev/live_controller.py --tests-dir C:/PythonDev/arduino-panel-checks-20261109-1146590d --output-dir <approved-artifacts>

Default requires exactly **74, zero skips**. Explicit --logic-only runs the
unchanged first 56 + review 11 = **67**, with zero skips, and is never labeled a
Windows all-74 result. The three original test files are LF-hash pinned; they
are never edited. For an LF candidate only, a disposable CRLF-exact normalized
copy satisfies the original deployment-newline assertion without changing it.
The selected original source hash remains in the receipt.

Namespace additions are pinned exact AST `_two_display_read_path`,
`_TWO_DISPLAY_LEGACY_FILES`, their literal prefixed constants, and the exact
`_two_display_thread_running` / `_two_display_running_threads` helpers. Only
missing inert owner interfaces (`setEnabled`, stopped hotkey/poller) are added;
old zero-argument wait callbacks are adapted to 1200 ms while still calling
those exact callbacks. Temporary interfaces are restored after close.
Original callbacks, AST preservation gates and all assertions remain intact.
Six negative controls reject mutated helper/map/destination/ownership methods
and incorrect timeout. New tests separately exercise actual persistence and
shutdown behavior; the wrapper is not a waiver of shutdown semantics.
Read-only Windows metadata enumeration stays in the original Qt suite, but
its raw metadata stdout is discarded from logs.

**Final 8d6 legacy gate resolved without masking:** Linux selected **67/67
passed, zero failures/errors/skips**, with the same six dependency negative
controls and unchanged original harnesses/wrapper. Source owner restored exact
baseline `_has_active_playback` and put `_arduino_before_activity()` at body[1]
after each activity docstring, while retaining the unchanged strong ownership
guard immediately afterward. Only those seven production methods differ from
b01. The new shutdown fixture executes the exact baseline cancellation hook
with inert operation-cancel/LED-stop recorders; all native and worker constructors
remain forbidden. A restore=False -> True mutation is rejected before execution.
Original callbacks, structural assertions and every original test remain intact.

## Independent P1 regressions and historical Linux freeze snapshot

The 9fa78e741d45 freeze is retained for **negative evidence, not release**.
Independent review found paused source steps swallowed by a large drift
threshold and close accepting a still-running QThread after bounded wait.
New regressions require +/-1 frame at 25 and 30000/1001 FPS, threshold 250,
missed seeking flags, pause transition, first/last clamp, negligible float
noise, retained master/test/calibration ownership and ignored/deferred close
until actual worker/helper completion. There is no audible master mutation,
video join in the MIDI worker or QThread.terminate workaround.

Historical Linux snapshot, **2026-11-09 before Windows final verification**:
immutable **8d6ab7966ee7c6e42032f5ff0758124c89a11b28fa63c3289866dc281c0c78d0**
(462028 LF bytes, 9563 LF, no CR) was tested: **130 non-Qt methods passed, zero
failures/errors**. Exact audible timing and the 72-case MIDI/master event matrix
passed. Source bytes stayed stable and the original LF hash stayed unchanged.
There are **146 authored methods across nine modules: 130 non-Qt + 16 real-Qt**.
Linux lacked PyQt6: all three Qt classes were unexecuted and not counted as
passes in that snapshot. `--require-qt` correctly returned nonzero with three
missing-dependency class errors and zero skips; it did not silently omit the
new lifecycle class. Windows subsequently executed and passed all 16 methods.

Prior-source evidence: b01 Windows 142/142 and native 8/8 passed; the parent
inspected 12 representative populated screenshots without new additive clipping.
The existing 12 Qt methods remain byte-identical (file SHA
e047b2dc1ea2d2ec224171218105b1d6debdf57f88040fd948cf4bff3ed89895).
Those older runs are not substituted for the final-source verification.

**Final installed Windows gate, 2026-11-09:** after the 20:38:40 UTC installation,
the exact final source passed 146/146 selected methods, all 74 unchanged Arduino
methods and all eight native own-pipe cases, with zero failures/errors/skips
where reported. The selected 108 existing checks and five Windows sensitivity
checks also passed. Windows Python 3.13.5 / Qt 6.9.0 / PyQt 6.9.1 executed all
16 real-Qt methods, including the four real-QThread methods. The independent
final seven-method review was approved (14 P1 checks / 42 blocked-entry cases).
This completes the selected offline gate, not live hardware qualification.

Portable negative sensitivity check:

    <python> -B checks/two_display/verify_negative_controls.py --source <frozen-candidate> --baseline <original> --prior-source <immutable-9fa-copy> --output-dir <isolated-artifacts>

`--prior-source` is optional; when supplied it must have exact 9fa LF hash.
The final harness passes its positive controls (6 methods), rejects the exact
cancellation-hook mutation before execution, and detects both disposable
close/early-delete AST mutations without errors. The old 9fa
paused/frame/retry checks fail 4 methods / 37 assertions / 0 errors, as required
for negative evidence. Existing retained pre-fix shutdown-negative logs remain
available to the parent; no input source is changed.
Earlier green drafts do not overrule newly discovered semantic failures.
STATUS.json records the final offline PASS and preserves the earlier Linux
snapshot separately; remaining gates are live hardware/playback checks.

Real Qt renders populated five-zone crop/stretch modes and both output states
at 1366x768 and 1920x1080, all composite/final/still tabs, plus main display/DP/
FPS controls and scroll-reachable legacy widgets. Missing saved and duplicate
profiles exercise the real safe profile/status handlers. The parent visually
reviewed selected screenshots; passing Qt assertions provide the geometry
checks recorded in qt_editor_traces.json / qt_main_traces.json. Of 79
final renders, 78 are byte-identical to b01, including 11 of the 12 previously
inspected representatives. The sole changed main-1366 render was fetched and
inspected, plus three final samples: no new additive clipping. Existing table
2:3 proportions/column widths remain exact; the small legacy track-name collapse
is not a new layout regression. No raw screenshots are published. Actual
font-metric requirements are compared with allocated content geometry.

When packaging, retain relative `checks/two_display/` and `tests/` layout and
include the unchanged empty `tests/__init__.py`; it prevents an installed
third-party `tests` package from shadowing these fixtures. `SHA256SUMS` lists
all needed harness/docs files, including parent-owned native proof unchanged.
The native proof ran against the exact final installed Windows artifact and
passed 8/8. Its scope is only own randomized test pipes, not live mpv endpoints.

## Focused real-QThread queued ownership gate

`test_two_display_qt_lifecycle.py` adds four methods (all three master/test/
calibration owner slots) without changing any existing Qt/render assertions:

- Actual QThread Event-wait work stays running while production wait(2500)
  times out; QWidget close is ignored, repeated close is idempotent, saves and
  shutdown callbacks happen once. A real QTimer releases the controlled Event.
- An early custom signal is genuinely queued to a GUI-affinity QObject slot;
  production completion must defer deletion while the real thread still runs.
- Late old-generation queued custom/actual finished signals cannot clear or
  delete a newer running owner; pending old ownership drains independently.
- Genuine QThread.finished releases the exact current owner and invokes
  deleteLater once; actual QObject destruction is observed before explicit
  widget close. GUI delivery, bounded waits and deletion ordering are traced.

Cleanup always releases every Event and uses bounded waits, never terminate.
Test QThreads have strong fixture ownership but no QWidget C++ parent, so a
detected premature-close regression can fail an assertion instead of aborting
the test process. A guarded deleteLater records a running-thread violation and
refuses the unsafe destruction; it does not turn that violation into a pass.
These are test-owned threads only; hardware/native/media dependencies remain
forbidden. The new class is included in `run_offline.py --require-qt`; allow
about 8 seconds for its three genuine 2500ms timeout cases plus event pumping.
`qt_lifecycle_traces.json` records the exact source hash, Qt/PyQt versions,
queued callback events and cleanup/deletion results. The installed Windows
execution passed all four methods: 12 scenarios / 15 test-owned QThreads, each
QObject destroyed once, every signal delivered on the GUI thread, zero Qt
errors. Linux compilation alone was not treated as execution proof.

## Frozen executed QA and documentation-only release handoff

The earlier transfer baseline was the parent-staged `SHA256SUMS` hash
2d01f0e592d4d59c1f2a0603d368950bfa10b8a243eb1ef01ed87765202118b4.
Its historical seven-file test-only delta added the lifecycle class and narrowly
adapted its fixture/runner/negative controls. No application source or runtime
data was included. That test delta is already frozen and executed.

The **executed QA manifest** SHA256 is
`b4e6bf2a8d9a0f6e7a52706a9c8d4919bd878f69ac167695bb886a7c0d58e0c7`.
All **13 nonempty Python harness files plus the empty `tests/__init__.py`
marker** remain identical to the Windows-executed pins. This final handoff
changes only `STATUS.json`, `TESTING.md`, `SHA256SUMS` and the new
`RELEASE_VERIFICATION.md`, all under `checks/two_display/`. The regenerated
manifest has 17 entries and excludes itself. Its documentation hashes differ
from the executed QA snapshot; none of the tested Python bytes changed.
Original/new application source hashes remain unchanged, and the installed
CRLF source normalized literally equals the repository LF bytes. Parent owns
Git/release operations; this documentation step does not perform them.

## Source formatting disclosure

The explicit untracked-source whitespace check reports **113 trailing-whitespace
warnings** (110 byte-exact baseline lines and three modified legacy-style lines;
original: 115). The tested source remains frozen. This is a disclosed formatting
finding, not a runtime failure; do not claim a clean full diff from tracked-only
`git diff --check`. See RELEASE_VERIFICATION.md for scope and parent staged gate.
