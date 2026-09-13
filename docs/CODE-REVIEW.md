# Event-generation code review — 2026-09-13

Reviewed baseline `6b9a8b8` after the earlier timing/trim interface review.
The recovered audit identified go/no-go feedback entering trial regressors.
This review reproduces the source defect with synthetic raw CSVs, fixes it,
and checks the rest of this package's entry points. It does not reproduce the
separate participant-level scientific report or downstream GLM audit.

## Surfaces inspected

| Surface | Contract and coverage |
| --- | --- |
| `cli.py`, `run.py` | Four commands; `create` consumes canonical `sub-*/ses-*/beh` CSVs, with a legacy `in_scanner_behavior` resolver. `run` requires ingested subjects and optionally copies practice/survey data. CLI routing and migrations have existing tests. |
| `create.py` discovery and identity | Task discovery from NIfTIs; task/run from CSV filenames; subject/session from directories. New CLI tests use two subjects, two sessions, and sibling runs with different scan lengths and discarded-volume counts. Canonical pairing remains upstream. |
| `utils.py` and event construction | Read every task column/condition lookup and cleanup, accuracy calculation, negative-RT clock reconstruction, trigger subtraction, units, missing-value handling, cue propagation, and renaming. New raw-to-BIDS tests focus on go/no-go, single stop, and the missing shape/cued-switch alias; existing dual-task controls remain. |
| Timing and QC output | Per-run dummy shift, first backward-onset cut, acquired NIfTI length, onset clipping, TSV writing and truncation sidecar. Existing tests cover individual cuts; a new combined-cut test checks independent denominators and duration preservation. |
| `migrate.py`, `config.py`, `qc_globals.py`, package metadata | Optional practice/survey copies, acquisition constants, and reference-only QC thresholds. No in-scanner migration restored. Package metadata no longer claims to trim NIfTIs. |

The superseded [manifest migration change](https://github.com/lobennett/network_events/pull/1)
was read for context. Its manifest paths/run reassignment concern deleted code;
it was neither merged nor closed.

## Confirmed defects and corrections

All reproductions are in [test_event_semantics.py](../tests/test_event_semantics.py).
They write synthetic jsPsych-style CSVs into a canonical sourcedata tree and call
the real `create` CLI with small synthetic BOLD NIfTIs and JSON metadata. The
fixtures follow the package's block-end clock, millisecond units, required task
columns, and response-sentinel contracts; they are not participant exports.

1. **Go/no-go feedback became a trial condition.** A `feedback_block` carrying
   `go` or `nogo` was classified using response accuracy before being renamed to
   `break` or `break_with_performance_feedback`. The TSV consequently contained
   `go`, `nogo_success`, or `nogo_failure` on nontrials. Classification now applies
   only to `test_trial`; other go/no-go rows have `trial_type=n/a`. The original
   `go_nogo_condition` remains as provenance. Removing inherited conditions masks
   the contamination (previously yielding `unknown`); downstream trial-ID guards
   also prevent it from entering regressors. Controls retain correct/wrong go
   responses, omissions, no-go success/failure, break IDs, and all event timing.

2. **Untimed rows shifted go/no-go labels.** Dropping a setup row with missing
   `block_duration` leaves gaps in the CSV index. Assigning a new default-index
   Series then aligned conditions to different rows: genuine go omissions could
   become no-go successes. Assignment now uses the retained row mask. The same
   export with and without an untimed setup row produces the same labels and timing;
   feedback still matches its original row index. Contiguous indices masked this
   defect in the old suite.

3. **Clock correction could fail on a removed predecessor.** With an RT below
   `-1` immediately after untimed metadata, looking up raw index `i - 1` raised
   `KeyError`; the CLI wrote an empty TSV. Reconstruction now uses the preceding
   retained row by position and keeps original indices for feedback matching.
   A drifting-clock fixture recovers the same hand-calculated onsets with and
   without the metadata gap. No RT below `-1`, or a present predecessor, masks
   the failure. A first timed row with negative RT still fails explicitly because
   there is no clock anchor. The existing duration-summing rule and raw RT values
   are unchanged.

4. **Missing feedback text discarded the whole run.** Null/numeric `stimulus`
   values caused `.lower()` errors; an absent column caused `KeyError` when a
   feedback ID was present. Nontext now supplies no performance-feedback match.
   The known feedback row remains a plain break, and trials survive. String-text
   controls still distinguish ordinary and performance feedback using the
   existing keywords. This does not infer performance feedback from absent text.

5. **Failed reruns left stale successful QC.** After a successful conversion,
   removing the trigger made the next run write an empty TSV while retaining the
   previous five-trial sidecar. The empty fallback now removes that run's stale
   truncation sidecar. Repeated successful runs are byte-identical, and restoring
   the input restores both outputs. A first failed run has no old sidecar to
   expose this bug. The CLI's existing warning/empty-TSV failure behavior remains.

6. **An untrimmed scan lost an event at exactly zero.** An early `> 0` filter
   rejected a trial beginning at the trigger, contrary to the documented
   `[0, scan_duration)` window. It now admits zero. Controls check untrimmed
   onsets `[0, 2]` and a trimmed run retaining only the second event at zero.
   A positive dummy shift masks the original scanner-zero boundary defect.

7. **A declared experiment alias could not generate events.**
   `shape_matching_with_cued_task_switching` was in the column/rename maps but
   missing from the condition map, causing `len(None)` and an empty TSV. It now
   uses the existing suffixed version's condition construction and cue response
   placeholder. Both spellings produce `tstay_cswitch` and preserve the separate
   shape condition. Using the `__fmri` spelling masked the missing lookup.

## Checks and contradictory evidence

Baseline: **48 tests passed despite the reproduced defects**. After the changes:
**69 tests passed**, including 21 new cases. Each corrected failure was observed
before its fix; controls exercise the corresponding masking conditions.

```bash
uv sync --frozen
uv run --frozen pytest -q --basetemp=.pytest_cache/audit-tmp
uv run --frozen python -m compileall -q src/network_events
git diff --check
```

Validation used Python 3.12.13 and the committed lock (including pandas 3.0.5,
NumPy 2.5.2, nibabel 5.4.2). No participant data, Sherlock runs, campaign changes,
or production event regeneration were used.

The neighboring stop cleanup already limits outcome classification to true
trials and preserves their labels across index gaps. Controls confirm this;
there is no evidence here to change its success criterion. It is not a universal
sanitizer: constructed stop feedback with inherited raw `go`/`stop` retains those
raw labels, although it does not acquire `stop_success`/`stop_failure`. This limits
the inference that stop-task masking alone prevents every form of contamination.
Downstream readers still need trial-ID guards, including for older event files.

The combined-cut control begins with five true trials, keeps two after the clock
cut, and loses one of those two to scan clipping: fractions `0.6` and `0.5`,
respectively. The final retained break keeps its six-second duration even when
its tail extends beyond the scan. These existing timing/counting rules were sound
in the exercised cases and were preserved.

## Limits and scientific choices

- This is source inspection plus bounded synthetic regression evidence, not a
  complete validation of every acquisition/export version. The extra sparse-row,
  alias, and failure cases establish code behavior, not participant prevalence.
- Identity depends on canonical input. Discovery filters task names, not complete
  acquisitions; duplicate/mismatched CSV identities, differently padded run
  tokens, and inconsistent multiecho metadata are not comprehensively validated.
  No new pairing or reconciliation rule was introduced.
- Feedback detection remains a keyword heuristic with ID/fallback precedence.
  Mixed feedback naming and other cue/stimulus layouts need acquisition-specific
  evidence before broader normalization. Condition/accuracy columns on nontrials
  are provenance, not permission to treat those rows as behavioral trials.
- Truncation metrics begin after onset/dummy filtering. `NTestTrialsRetained`
  describes the clock cut, before scan clipping; `ScanDurationSeconds=null` means
  scan clipping could not be measured. A failed conversion now has no sidecar,
  not a fabricated zero-loss report. Missing/malformed evidence policy belongs
  downstream. Backward jumps masked by prior filtering and the validity of
  duration-based clock reconstruction are not resolved by this audit.
- Ordinary-break regressors, response-time modeling, exclusion thresholds,
  alternate accuracy definitions, and changes to event-duration/truncation policy
  remain scientific decisions. None was selected here. Passing tests alone does
  not establish scientific correctness or justify rerunning participant data.
