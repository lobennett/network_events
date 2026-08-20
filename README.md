# network_events

Behavioural CSV → BIDS `_events.tsv` for the r01network study. Study-specific: the jsPsych
battery, task naming and acquisition constants (`TR_SECONDS`, `N_DUMMY` in `config.py`) are
hard-coded, and it is not a general-purpose library.

Normally invoked as stage 10 of `network_fmri pipeline`, which pins this package at a commit.

## Install

```bash
uv sync          # Python >=3.11; on a compute node, not a login node
```

## Commands

```bash
network-events create --sourcedata sourcedata --bids-dir .     # the one that matters
network-events run --behavioral-dir <raw> --bids-dir <BIDS>    # create + optional migrations
network-events migrate-archive --raw-dir <raw> --output-dir sourcedata
network-events migrate-survey --survey-root <survey> --output-dir sourcedata
```

`create` reads `sourcedata/sub-*/ses-*/beh/*_beh.csv` — one CSV per BOLD run, already paired —
and writes `_events.tsv` beside each BOLD. The pairing is not done here: it is frozen in the
canonical dataset on `$OAK` and copied in by `network_fmri ingest-beh`, which is why there is no
reconciliation manifest or review gate any more.

The two `migrate-*` commands move out-of-scanner practice data and prescan surveys into
`sourcedata/`. They are optional and touch nothing `create` reads.

## What `create` does to the timing

Three transformations, in order. All three are data-integrity fixes applied unconditionally —
none is an exclusion decision, and none of them can fail loudly, so each is measured instead.

**1. Onset shift.** `network_fmri trim` drops the first 7 volumes of every BOLD, so a trimmed run
starts `7 × 1.49 = 10.43 s` later than the scanner did. Onsets shift by −10.43 s and anything
landing before zero is dropped. The per-run truth comes from the sidecar
(`NumberOfVolumesDiscardedByUser × RepetitionTime`), so an untrimmed run shifts by 0 and the
correction cannot be applied twice.

**2. Non-monotonic truncation.** The raw jsPsych `time_elapsed` clock occasionally jumps backward
mid-run — an ExpFactory logging glitch we cannot trace or fix at source. Absolute timing is
unreliable past the jump, so the run is cut at the first backward step and only the clean
monotonic prefix is kept.

**3. Scan-length clip.** A run aborted at the scanner leaves the behavioural session running, so
the CSV describes trials that were never imaged; keeping them puts regressors past the end of the
timeseries. Onsets are clipped to the acquired length, read from the NIfTI rather than the
sidecar because `NumberOfTemporalPositions` records the *intended* volume count — one scan claims
524 volumes for 223 acquired.

`duration` is deliberately not clipped, so a final trial's box-car may end a few seconds past the
last volume. The trial was presented and its onset is inside the scan; the design matrix simply
has no timepoints for the tail. Truncating `duration` would misstate the stimulus.

## The QC seam

Both truncations drop trials, and neither this package nor `create` decides whether that loss is
survivable. It writes the numbers to
`sourcedata/events_qc/<sub>/<ses>/<sub>_<ses>_task-<T>_run-<N>_desc-truncation.json`:

```json
{"NTestTrialsExpected": 40, "NTestTrialsRetained": 12, "FractionTestTrialsDropped": 0.7,
 "ScanDurationSeconds": 59.6, "NScanTestTrialsDropped": 26,
 "FractionScanTestTrialsDropped": 0.65}
```

The first three describe the non-monotonic cut, the `Scan*` keys the clip to the acquired
scan. [`network_qa`](https://github.com/lobennett/network_qa) reads them and applies the
threshold.

The sidecar lives under `sourcedata/` with a non-reserved `_desc-truncation` name rather than as
an `_events.json` in `func/`: BIDS reserves the latter for events-column descriptions and
bids-validator rejects it.

## Layout

```
src/network_events/
  cli.py         four subcommands
  run.py         orchestration: create, plus the optional migrations
  create.py      CSV -> events.tsv, and the three timing transformations
  migrate.py     out-of-scanner and survey data -> sourcedata/
  utils.py       shared helpers (incl. find_nonmonotonic_cut)
  config.py      TR_SECONDS, N_DUMMY -- vendored, so no dependency on network_fmri
  qc_globals.py  per-task behavioural thresholds; reference only, unused
```

## Tests

```bash
uv run pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md).
