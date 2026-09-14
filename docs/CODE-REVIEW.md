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
| `utils.py` and event construction | Read every task column/condition lookup and cleanup, accuracy calculation, negative-RT clock reconstruction, trigger subtraction, units, missing-value handling, cue propagation, and renaming, including the order the pipeline applies them in. New raw-to-BIDS tests cover go/no-go, all three stop tasks, and the shape/cued-switch, flanker/cued-switch, and shape/spatial-switch aliases; existing dual-task controls remain. |
| Timing and QC output | Per-run dummy shift, first backward-onset cut, acquired NIfTI length, onset clipping, TSV writing and truncation sidecar. Existing tests cover individual cuts; a new combined-cut test checks independent denominators and duration preservation. |
| `migrate.py`, `config.py`, `qc_globals.py`, package metadata | Optional practice/survey copies, acquisition constants, and reference-only QC thresholds. No in-scanner migration restored. Package metadata no longer claims to trim NIfTIs. |

The superseded [manifest migration change](https://github.com/lobennett/network_events/pull/1)
was read for context. Its manifest paths/run reassignment concern deleted code;
it was neither merged nor closed.

## Confirmed defects and corrections

Reproductions are in [test_event_semantics.py](../tests/test_event_semantics.py)
and [test_dual_task_fixups.py](../tests/test_dual_task_fixups.py). CLI cases write
synthetic jsPsych-style CSVs into a canonical sourcedata tree with small synthetic
BOLD NIfTIs and JSON metadata. Other cases call `create_events_df` directly,
including TSV roundtrips for GLM subset checks. The fixtures follow the package's
block-end clock, millisecond units, required task columns, and response-sentinel
contracts; they are not participant exports.

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

8. **Stop-task fixation rows were never relabelled.** The three stop cleanups
   matched the canonical `test_fixation` id, but `_rename_cells` — which is what
   maps the raw `fixation`/`ITI_fixation` label onto it — ran *after*
   `response_time_and_junk`, so the mask was empty on real exports and the
   fixation row kept whatever `stop_signal_condition` it inherited. Renaming now
   happens immediately after `add_cols`, before any cleanup, so every cleanup
   sees canonical ids. The stop regression writes the raw `fixation` label and
   checks the emitted row is `test_fixation`/`fixation` with unchanged onsets
   and durations. Fixtures that wrote `test_fixation` straight into the raw CSV
   masked this. Nothing else keys off a renamed id, so trial classification,
   accuracy, and timing are unchanged; the rename is value-only and the rows it
   touches are the same ones either way.

9. **Breaks could inherit trial conditions across tasks.** `add_cols`
   copies a condition column onto rest/feedback rows, and only the go/no-go
   cleanup scoped it. `break` and `break_with_performance_feedback` rows now get
   `trial_type=n/a` at a single shared boundary in `_build_events_df`, after
   feedback identification. This is deliberately limited to breaks: every other
   event keeps its canonical `trial_id`, timing and source columns, and
   `test_trial` classification is untouched. The task-specific distinction
   between event identity and condition labels is documented in
   [README's event-column contract](../README.md#event-columns-and-labels).
   No inspected consumer requires one battery-wide nontrial condition vocabulary.
   The stop regression covers break scoping with and without inherited raw
   `go`/`stop` labels and verifies that the source column survives.

10. **A widened substring silently changed a second task.** Relaxing
    `"cued_task_switching_" in exp_id` to `"cued_task_switching"` for the cue
    response placeholder picked up two bare aliases, not one:
    `shape_matching_with_cued_task_switching` (intended, item 7) and
    `flanker_with_cued_task_switching` (unrecorded). The parity is correct — a
    cue screen accepts no response in either spelling — so the check is now an
    explicit `_CUE_RESPONSE_PLACEHOLDER_EXP_IDS` set naming all seven affected
    exp_ids rather than a substring that would silently absorb the next alias.
    The cuedTSWFlanker fixture previously left the cue's `correct_response`
    null, which masked the change; a new case plants a real raw value on the cue
    row, asserts it is replaced, and asserts the trial row's response and the
    already-scored accuracy are unaffected. This closed the *placeholder*
    divergence only; the `trial_type` divergence for the same aliases is item 11.

11. **Declared aliases emitted a different `trial_type` vocabulary.** Several
    exp_ids are declared in both a `__fmri` and a bare spelling, and the
    acquisition writes whichever one that experiment's `experiment.js` happens
    to set — so both name the same task and both must satisfy the same
    downstream selector. Two pairs diverged, in opposite directions:

    * `flanker_with_cued_task_switching__fmri` folded the flanker factor into
      the composite (`cswitch_tstay_incongruent`) and shifted it by one row,
      while the bare spelling emitted `switch_stay` with `flanker_condition` in
      its own column. The GLM config crosses those two columns into its six
      cells, so the suffixed spelling matched none of them. The suffixed
      special-case and its `shift(1)` are removed; both spellings now take the
      generic two-factor path plus the existing cue→trial propagation in
      `_build_events_df`, which fills only missing trial-row values.
    * `shape_matching_with_spatial_task_switching` (bare) kept the
      acquisition's `td_{same,diff,na}` task-dimension prefix
      (`td_same_tstay_cswitch_SSS`), which the suffixed spelling strips. The GLM
      config names the 21 switch-by-shape cells without it, so the bare
      spelling matched none of them. The strip now applies to both spellings.
      The bare spelling was also missing from `_RENAME_CELLS_LOOKUP`, so its
      `feedback_block` never became `break` and the item-9 boundary could not
      see it; its rename map is added.

    Both corrections preserve onsets, durations, responses and the separate
    source columns; no factor is added or dropped. The regressions run raw CSVs
    through `create_events_df`, serialize to TSV, reload as the GLM runner does,
    and evaluate that config's literal `subset` expressions with
    `DataFrame.query` — six flanker cells and all 21 shape cells, once each, for
    both spellings, plus ordinary-break and performance-feedback
    counterfactuals. Testing only one spelling per pair masked all of this.

12. **A dead `memory_cue` branch.** `_cleanup_stop_signal_w_directed_forgetting`
    ended with a `trial_type == "memory_cue"` condition that cannot fire: the
    mask restricts it to `test_trial`, the forget cue is renamed `test_cue`, and
    `add_cols` builds this task's `trial_type` as
    `stop_signal_condition_directed_forgetting_condition`. Removed without
    behavior change. It is not a missing regressor: the GLM selects the letter
    set and the forget cue by `trial_id` (`test_stim`/`test_cue`) and uses their
    recorded durations regardless of `trial_type`. A new control walks the raw
    ITI → letter set → cue → fixation → probe sequence and checks those rows
    survive with 2 s and 1 s durations and are never relabelled.

13. **Prefix removal erased already-normalized switch factors.** After alias
    parity was restored, the shape/spatial path still dropped the first two
    tokens unconditionally. A minimal trigger-plus-trial CSV with
    `predictable_condition=tstay_cswitch` and shape `SSS` emitted only `SSS`,
    matching none of the intended switch-by-shape cells. Prefix handling now
    follows the [event-column contract](../README.md#event-columns-and-labels).
    Twelve real-CLI cases cover both aliases: the three acquisition prefixes
    mask the old defect,
    while normalized values, unknown prefixes and a non-leading `td_same_`
    expose it. Six cases failed before the fix; all now preserve the expected
    label, timing and behavioral columns. Unknown text remains unmodeled rather
    than being coerced into an existing cell. This counterfactual does not
    establish how often normalized raw exports occur in participant data.

## Checks and contradictory evidence

Baseline: **48 tests passed despite the reproduced defects**. After the changes:
**92 tests passed**, including 44 new cases. Each corrected failure was observed
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

The stop cleanups limit outcome classification to true trials and preserve
their labels across index gaps; controls confirm this and there is no evidence
here to change their success criterion. Their fixation relabel, however, was
dead until item 8, and neither they nor any other cleanup scoped breaks until
item 9. Scoping is now split by responsibility: a cleanup decides what a task's
own event types mean, and the shared boundary in `_build_events_df` decides that
a break is not a trial. That boundary covers all twenty-two declared exp_ids,
including the eighteen with no cleanup entry. It is still not a universal
sanitizer — any *other* non-trial id in a task without a cleanup keeps whatever
condition `add_cols` copied onto it — so downstream readers still need trial-ID
guards, including for already-written event files.

Both dual stop tasks are now exercised from their raw fixation spellings as
rename-order controls: `stop_signal_with_flanker__fmri` from `fixation`, and
`stop_signal_with_directed_forgetting__fmri` from both `ITI_fixation` and
`fixation`. Fixation is not uniformly a no-response interval in the acquisition
— the first go/no-go test block and the stop/DF ITI accept keys — so recorded
responses on those rows are left alone and trial status is not inferred from
key availability.

The combined-cut control begins with five true trials, keeps two after the clock
cut, and loses one of those two to scan clipping: fractions `0.6` and `0.5`,
respectively. The final retained break keeps its six-second duration even when
its tail extends beyond the scan. These existing timing/counting rules were sound
in the exercised cases and were preserved.

## Limits and scientific choices

- This is source inspection plus bounded synthetic regression evidence, not a
  complete validation of every acquisition/export version. The extra sparse-row,
  alias, and failure cases establish code behavior, not participant prevalence.
- GLM subset tests transcribe the task YAML at network_glm commit
  `122fa29cd11e724a6cfc8160841bcfc537bb2c82`; they check emitted-event behavior
  against that contract, not future drift in the separate repository.
- Identity depends on canonical input. Discovery filters task names, not complete
  acquisitions; duplicate/mismatched CSV identities, differently padded run
  tokens, and inconsistent multiecho metadata are not comprehensively validated.
  No new pairing or reconciliation rule was introduced.
- Feedback detection remains a keyword heuristic with ID/fallback precedence.
  Mixed feedback naming and other cue/stimulus layouts need acquisition-specific
  evidence before broader normalization. Condition/accuracy columns on nontrials
  are provenance, not permission to treat those rows as behavioral trials. Break
  scoping keys off the canonical `break` ids, so a task whose rest screen is
  named something else is out of its reach; clearing `trial_type` on every
  non-`test_trial` row instead would also erase named cues and fixations and was
  not selected. Alias parity is resolved per pair against that task's existing
  selector, not by treating the `__fmri` spelling as authoritative; for
  shape/spatial the bare spelling's historical export provenance was not
  established, and it is corrected as a declared alias of the same task.
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
