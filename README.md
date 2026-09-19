# network_events

`network_events` converts the canonical r01network behavioral CSV files into BIDS
`_events.tsv` files. It is a study-specific package for the jsPsych battery and is
normally run as a stage of the `network_fmri` pipeline.

The public command line interface has exactly two commands: `audit` checks the
canonical identity contract and `create` converts every audited behavioral run.
Data preparation and quality policy belong to the surrounding pipeline and to
[`network_qa`](https://github.com/lobennett/network_qa).

## Install

```bash
uv sync                  # Python >= 3.11
```

## Canonical layout

Behavioral input is rooted at `sourcedata/behavioral` and must contain one file
per logical non-rest BOLD run:

```
sourcedata/behavioral/
  sub-01/ses-01/beh/sub-01_ses-01_task-nBack_run-1_beh.csv
```

The matching BOLD file is under the BIDS `func` directory. Echoes are treated as
one logical run. Identity matching is exact: subject, session, task, and run must
match the BOLD filename and its `sub-*/ses-*/func/` parents, and the behavioral
file must be in the matching `sub-*/ses-*/beh/` directory. BOLD supports `.nii`
and `.nii.gz`; duplicate encodings, mixed echo/non-echo images, and entity
variations other than unique numeric echoes fail the audit. Rest runs do not
require behavioral input.

If a run has no behavioral file, a reviewed exception can satisfy the audit. Put
`behavioral_exceptions.tsv` at the behavioral root with these required columns:

```text
subject  session  task  run  reason  detail  reviewed_by  reviewed_at
```

Every field is required, identities use BIDS labels, and duplicate or orphan
exceptions fail the audit. The `audit` command prints JSON containing `pairs`,
`bold_groups` (the physical images for each logical run), `exceptions`, and `errors`; use `--json PATH` to save the same payload.

## Commands

```bash
network-events audit  --bids-dir . --behavioral-dir sourcedata/behavioral
network-events create --bids-dir . --behavioral-dir sourcedata/behavioral
```

`audit` exits 0 only when both input roots are existing directories and every non-rest BOLD
has exactly one canonical behavioral file or reviewed exception. `create` runs the
same audit first, then writes one events file beside each matching BOLD:

```
sub-01/ses-01/func/sub-01_ses-01_task-nBack_run-1_events.tsv
```

Each conversion is represented by a structured result. Successful runs report
`created`; failed runs report `failed` and remove partial output. All failures are
also written to `sourcedata/events_qc/conversion_errors.tsv` with the columns
`subject`, `session`, `task`, `run`, `source_path`, `exception_class`, and
`message`. Thus a conversion error remains visible instead of becoming an empty
events file.

## Timing transformations

`create` applies these data-integrity transformations in order:

1. Onsets are shifted by the discarded-volume count times `RepetitionTime` from
   the run's BOLD sidecar. Events before time zero are dropped. An untrimmed run
   must explicitly record a discarded-volume count of zero.
2. Events are truncated at the first backward step in the raw `time_elapsed`
   clock. Absolute timing after that logging discontinuity is not reliable.
3. Events are clipped to the acquired NIfTI scan length. The sidecar's intended
   volume count is not used for this check.

Every physical BOLD image must have a readable sidecar with a nonnegative integer
`NumberOfVolumesDiscardedByUser` and finite positive `RepetitionTime`, plus a
readable 4-D NIfTI with positive acquired duration. Sidecar and header TRs must
agree, and echoes must agree on TR, discarded volumes, and acquired volume count.
Headers with unspecified temporal units retain the historical seconds convention.
Missing, invalid, or conflicting timing evidence produces a conversion-error row
and no events file. There is no fallback to study constants or disabled clipping.

`create` exits 0 when every audited pair has either a valid events file or a
recorded conversion failure; identity-audit errors exit 2 before conversion.

Durations are preserved when an onset survives the scan-length clip. The command
also writes truncation measurements to
`sourcedata/events_qc/<sub>/<ses>/*_desc-truncation.json`, including expected and
retained test trials, dropped-trial fractions, scan duration, and scan-clip
counts. `network_events` records these facts; `network_qa` decides whether the
loss is acceptable and applies study thresholds.

## Package layout

```
src/network_events/
  cli.py       the `audit` and `create` commands
  identity.py  exact BOLD/behavior identity audit and exception schema
  create.py    CSV conversion, timing transforms, and structured errors
  config.py    study timing constants
  utils.py     shared timing and event helpers
```

## Tests

```bash
uv run --frozen pytest -q
uv build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development conventions.
