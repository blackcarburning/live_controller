# Final selected offline release verification

**Verified 2026-11-09, 2026-11-09T20:40:48.752766+00:00.**

- **Offline release qualified: true. Live hardware qualified: false.**
- Results cover selected offline suites, isolated real Qt/widgets/QThreads,
  native own-pipe interoperability and visual review. They are **not** a
  full-repository-suite pass or a production timing/playback qualification.
- The parent performed the Windows installation and verification. This final
  handoff is documentation-only; it does not edit Python/application/original
  tests, launch the controller, write Windows or mutate Git.

## Exact source and execution identity

| Artifact | SHA256 |
| --- | --- |
| Final repository LF source | `8d6ab7966ee7c6e42032f5ff0758124c89a11b28fa63c3289866dc281c0c78d0` |
| Final installed Windows CRLF source | `928410adbcfaf7b11157f3381873d5ff512b1910542f7563117151ce805b845b` |
| Unchanged original LF source | `605e78b10af95828d2d09df8eb14aa5c85828be4dd73bc467d96b11ff237c346` |
| Unchanged original Windows CRLF source | `56a91df1849bc879584a1ec3cecec2cbdf8222282a21263758cb975c3363e4ee` |
| Executed QA manifest, before this documentation refresh | `b4e6bf2a8d9a0f6e7a52706a9c8d4919bd878f69ac167695bb886a7c0d58e0c7` |
| Parent final installed summary | `b1f920ea5390040f166163a3fa2305d51472bd7cb5776339ea6b8cbdb3aea750` |

The final LF source is 462028 bytes / 9563 LF / zero CR; its installed Windows
form is 471591 bytes / 9563 CRLF. Installation completed at
**2026-11-09 20:38:40 UTC**. The parent retrieved the actual installed Windows
source and verified literal equality after normalizing its CRLF bytes to LF,
not merely matching an AST. Both original and new source hashes stayed
unchanged during this documentation refresh. The original source and monitored
legacy runtime data also remained stable after the Windows tests. The controller was never
launched.

Windows runtime: **Python 3.13.5, 64-bit AMD64; Qt 6.9.0; PyQt 6.9.1**, with
offscreen Qt for the isolated widget checks. No package install/update is part
of this qualification.

The executed pins cover **13 nonempty Python harness files plus the unchanged
empty `tests/__init__.py` package marker** (14 Python entries). Every one
remains identical to the parent summary's Windows-tested hashes. The new
`SHA256SUMS` has **17 entries excluding itself**: those 14 Python entries and
three documentation files. Its hash intentionally differs from the executed QA
manifest hash: only documentation changed after that run.

## Final installed Windows results

| Gate | Result and precise scope |
| --- | --- |
| Selected new offline suite | **146 passed, 0 failures/errors/skips**; 130 non-Qt + 16 real-Qt methods across nine modules. Rerun after installation. |
| Existing Arduino checks | **74 passed, 0 failures/errors/skips**; original assertions/files unchanged; six dependency-negative controls also verified. Rerun after installation. |
| Native transport | **8 passed**, rerun after installation; only the test's own in-process randomized Windows pipes, no mpv/external endpoint. |
| Selected existing regressions | **108 passed** in five unchanged selected modules: **three mirror seams and two actual AST seams**, using the identical final-byte nested alias fixture. Not full-suite coverage. |
| Windows sensitivity | **5 checks**, all expected negative behaviors detected. No source mutation was deployed. |
| Actual QThread lifecycle | Four methods / **12 scenarios / 15 test-owned QThreads**; all QObject destructions exactly once, all queued deliveries on the GUI thread, **0 Qt errors**. Included in the 146, not extra tests. |

The four selected positive suites total **336 passing checks** (146 + 74 + 8 +
108); sensitivity controls and lifecycle scenarios are not added to that total.
The real-QThread fixtures run only Event-controlled fake work on actual
QThreads with queued custom/finished signals and QTimer. Extracted production
completion/close guards execute on a QWidget SafeHost: close remains ignored
and repeated close idempotent until actual exit; early custom completion cannot
delete a running thread; stale-generation signals cannot replace a new owner;
actual finish releases/deletes once before close. Cleanup is bounded and always
releases controlled Events; it never uses terminate. No actual controller,
MIDI worker, native/media worker or player is constructed.

The source/AST gates retain exact audible timing/release structure and the
72-case fake MIDI/master ordering matrix. This is source/ordering evidence,
**not measured production timing**. The parent reports the independent final
seven-method review **APPROVED**, including 14 P1 checks and 42 blocked-entry
cases.

## Receipt hashes (raw private artifacts not published)

| Receipt | Bytes | SHA256 |
| --- | ---: | --- |
| selected146 | 19023 | `2fc4b77b7d6d92b558fefa7d6674c8e0ca10b3daadce4863325acf0def4081db` |
| arduino74 | 11932 | `80008eb8d87423f41343fc8c6b5b7b04cbb795584220f73411eccf0260a897cd` |
| native8 | 1508 | `e5259bf0b15f13f284ab5c942cc93c3778161141d90fa22e2e0355756da894c5` |
| selected108 | 1884 | `ffbdbb284061c9031889c3f5fe466d2f9ee24643bde6c6695826a9bcd3cfeb2a` |
| negative_sensitivity | 3178 | `ce143385471c42a50065c3826821da64d3cdf7525fffdcf9b40b1783eccda24d` |
| installation | 1222 | `c0daeac64f33365e9157dafd9e275e145bcef63f395dd1b2a97991d77bfbad88` |

The real-QThread lifecycle trace SHA256 is
`14bea5504431d648da21aedb42f4668ceaac17d127ab17b927363c22e066d7b4`.
Only hashes and bounded summaries are published here: no raw screenshots,
runtime configuration, endpoints, hardware identifiers or private payloads.

## Isolated visual review

The parent verified **79 final offscreen screenshots**; **78 are byte-identical
to b01**, including 11 of the 12 previously inspected representatives. The
sole changed main-1366 render was fetched and inspected, together with three
final samples. No new additive clipping was found. Existing table 2:3
proportions and column widths are exact; the small legacy track-name collapse
is a baseline behavior, not a new layout regression. This is isolated widget
render evidence, not a claim about actual monitor output. No screenshots are
added to the release documentation.

## Formatting finding — source remains frozen

**Whitespace lint is not clean.** An explicit untracked-file check,
`git diff --no-index --check /dev/null live_controller_two_display.py`, reports
**113 trailing-whitespace warnings** (exit status 3). The parent identified
110 as byte-exact baseline content and three on modified legacy read-path /
exception lines retaining that style; the original has 115 such warnings.
This is a nonbehavioral formatting finding, not a runtime test failure. The
fully tested installed source stays frozen: no whitespace cleanup or source
hash change is made. A tracked-only `git diff --check` is **not** evidence that
this new source file is lint-clean. The parent owns the final staged check of
the exact 113 source warnings and absence of warnings in other release files.

## Historical Linux snapshot — 2026-11-09, before final Windows verification

The final LF freeze passed **130 non-Qt methods**, zero failures/errors; three
Qt classes were skipped because Linux lacked PyQt6. The required-Qt invocation
correctly failed with three dependency errors instead of silently passing.
Those are historical Linux limitations, **not current pending Windows gates**:
the later Windows run executed all 16 real-Qt methods with no skips.

Linux also passed the **67 selected unchanged Arduino logic methods**, zero
failures/errors/skips, with six dependency negatives; that result was never
called the Windows all-74 run. Six positive sensitivity methods passed;
close-while-running and early-delete mutations were detected (three and one
assertion failures respectively), the cancellation-hook mutation was rejected
before execution, and the old 9fa paused behavior failed four methods / 37
assertions with zero errors as intended. Compile-only checks covered the 13
nonempty Python files. Earlier b01 142-method/native runs and broader LUFS
discovery records are prior evidence, not substitutions for final-source runs
and not a full-suite release pass.

## Remaining live qualification

**Untested:** installed/live mpv version and option support; actual HDMI/DP
screens and physical hotplug; real audio/MIDI operation, synchronization and
production timing under load. No application launch or hardware playback was
performed. Simulated permission/read-error paths do not establish an actual
operating-system permission condition. Offline qualification does not imply
any of these live gates passed.

The final documentation delta is exactly:

- `checks/two_display/STATUS.json`
- `checks/two_display/TESTING.md`
- `checks/two_display/SHA256SUMS`
- `checks/two_display/RELEASE_VERIFICATION.md` (new)

All application/original-test/Python harness bytes remain frozen; the parent
owns final commit, push and release operations.
