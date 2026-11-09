# Frozen GUI-modernisation offline checks — 2026-11-09

Seven reviewed scripts are copied byte-for-byte; SHA256SUMS also covers the small
snapshot helper and this README. No large source snapshots, screenshots, secrets
or device metadata belong here. Run with Python 3.12+ and -B; full Qt checks need
an existing verified Windows Python/PyQt6/pyserial environment.

## Exact inputs

From the repository root, create a **new empty scratch directory outside Git**,
then substitute its absolute path for <SCRATCH>:

~~~text
python -B checks/gui_modernisation/prepare_snapshots.py --repo . --output-dir "<SCRATCH>"
~~~

The helper uses read-only git show pre-gui-modernisation-20261109:live_controller.py,
checks the peeled tag commit e0f1f6be9641c5bb611102903899a90919b5ae01, and prepares
baseline.py/candidate.py with CRLF bytes. It refuses changed hashes or existing
output; never imports either source. Git/working-copy LF and CRLF pins:

| Input | SHA256 |
| --- | --- |
| Baseline LF | 605e78b10af95828d2d09df8eb14aa5c85828be4dd73bc467d96b11ff237c346 |
| Baseline CRLF | 56a91df1849bc879584a1ec3cecec2cbdf8222282a21263758cb975c3363e4ee |
| Candidate LF | 64d017ce7635598156a8328d5123bbf8744ca8630e950f09fdb0088631f076b5 |
| Candidate/installed Windows CRLF | 05ca1aa58da4a4c38e4cf40c4322efd0c4d7259bf446f642e41d66569b125896 |

Verify SHA256SUMS after transferring scripts and exact snapshots to authorized
Windows scratch space. The helper avoids shell-redirection newline/encoding
changes. Replace python with the verified interpreter; adjust script paths for
transferred copies. **Do not launch live_controller.py.**

## Commands (repository root)

~~~text
python -B checks/gui_modernisation/test_gui_modernisation.py --source "<SCRATCH>/candidate.py" --baseline "<SCRATCH>/baseline.py" --screenshot-dir "<SCRATCH>/main-renders"

python -B checks/gui_modernisation/test_gui_modernisation_dialogs.py --candidate "<SCRATCH>/candidate.py" --candidate-sha256 05ca1aa58da4a4c38e4cf40c4322efd0c4d7259bf446f642e41d66569b125896 --baseline "<SCRATCH>/baseline.py" --screenshots-dir "<SCRATCH>/dialog-renders"

python -B checks/gui_modernisation/run_gui_arduino_regressions.py --source "<SCRATCH>/candidate.py" --tests-dir checks/gui_modernisation --baseline "<SCRATCH>/baseline.py"

python -B checks/gui_modernisation/run_gui_repository_regressions.py .
~~~

- Main: real isolated widgets/state/events/geometry at 1366×768 and 1920×1080.
- Dialogs: three dialogs × two resolutions; **create dialog-renders first**.
  The explicit final candidate hash is mandatory: the unchanged script defaults
  to an older candidate. Independent dialog/helper AST pins still apply.
- Arduino: **74 tests, zero skips** = 56 panel + 11 review + 7 real Qt. The last
  Windows-only test performs authorized read-only SetupAPI **metadata enumeration**,
  never serial opens; retain raw metadata logs privately. On non-Windows use
  --suite mocked for **67**, not 74. Run included originals through this wrapper:
  one XR12 palette/style-only equality adaptation is fail-closed AST-verified,
  with seven business-mutation negatives; original bodies/assertions stay intact.
- Repository: **selected 108**, not full discovery. It adapts function-style
  zoom/MK helpers without pytest; some existing tests mirror helpers, others
  extract actual source.

Source-only alternatives: main --ast-only, dialogs --static-only, Arduino
--verify-only. These do not prove Qt runtime behavior. Never suppress nonzero exits.

## Evidence and limitation

**Packaging recheck, Linux/WSL Python 3.12.3:** all eight scripts compile; copied
hashes match; exact snapshots and reject-changed-input/refuse-overwrite controls
pass. Main AST passes 17 original + 5 helper negatives; all three dialog static
contracts pass; Arduino preflight + **67 mocked tests** and **selected 108** pass,
zero failures/errors/skips. PyQt6/pyserial are absent here; no Windows node touched.

**Full existing unittest discovery is NOT green.** Disposable pre-GUI and final
candidate copies ran the same unchanged command:

~~~text
python -B -m unittest discover -s tests -v
~~~

Both: **111 cases, 2 failures + 20 errors, zero skips, exit 1**. Exact ordered
case/subtest IDs, statuses, exception types/messages match in recording runs. All
22 problem entries are in test_xr12_lufs_integration.py: mostly missing _update_lufs,
plus baseline config/close-guard/fade/API expectations. These predate the GUI.
No existing tests/business logic were changed or failures hidden; the selected
108 is not a full-suite pass. Unittest does not collect function-style zoom/MK tests.

**Release-owner Windows report, 2026-11-09, after guarded 17:43 UTC install:** actual
C:/PythonDev/live_controller.py passed main checks at both resolutions (four full
185-character five-zone fixtures; XR12 visible across tabs/modes), six dialog runs
and all seven multi-zone tabs, and **74 Arduino tests with zero failures/errors/
skips**. Installed candidate hash above was unchanged before/after each; the
baseline backup was verified and final main PNG visually inspected. This is the
release owner's evidence, not a Windows rerun by the packager.

Evidence outside Git:
- /tmp/gui-modernisation-discovery-comparison.json plus matching -baseline.log,
  -candidate.log and -*-outcomes.json: exact failure/subtest comparison.
- /tmp/gui-modernisation-repository-final-selected108-tests.log and
  /tmp/gui-modernisation-selected108-result.json: final selected run.
- /tmp/gui-modernisation-repository-final-tests.log: earlier full discovery,
  preserved, not relabelled as a pass.
- /tmp/gui-modernisation-packaged-checks-result.json and
  /tmp/gui-modernisation-snapshot-preparation-result.json: packaging checks.
- Windows release-owner stage candidate-05ca1aa5: installed-main.stdout.log,
  installed-dialogs-r2.stdout.log, installed-arduino74.stderr.log (private).

## Safety

GUI gates parse/compile and AST-extract reviewed code into synthetic hosts; no full
controller import, constructor, app startup, hardware opens, MIDI or hotkeys. Mock
Arduino tests use fake handles/temp files. Qt/offscreen/font changes are process-local;
only explicit renders/test artifacts are written. SetupAPI metadata is the sole
real-device enumeration in the Windows suite. Playback, physical hardware, OS
chrome/DPI, canvas painting/dragging and real dialog save/preview lifecycles remain
unproved. AST extraction is a regression seam, not a hostile-code sandbox. Keep
all generated artifacts outside Git.
