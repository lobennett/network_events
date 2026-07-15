# network_events

Study-specific behavioral + BIDS event-generation pipeline for the r01network
project: raw jsPsych CSV -> BIDS `sourcedata` + `_events.tsv` + behavioral QC +
NIfTI trim.

This package owns the **behavioral half** of the pipeline end-to-end. It is
study-specific (r01network jsPsych battery, task naming conventions, and
acquisition constants are hard-coded), not a general-purpose library. It has
zero dependency on other `network_*` packages: the two acquisition constants
it needs (`TR_SECONDS`, `N_DUMMY`) are vendored locally in `config.py`.

Behavioral QC *computation* lives here (`qc.py`); integrating QC-derived
exclusions into a study-wide compiled-exclusions/provenance system is the
responsibility of the separate `network_qa` package (not yet built).

### Non-monotonic-onset truncation + trial-retention metric

Occasionally the raw jsPsych `time_elapsed` clock jumps backward mid-run (an
unrecoverable ExpFactory logging glitch). `network_events.create.create_events_df`
always truncates the run at the first backward onset step, keeping only the
clean monotonic prefix -- this is a data-integrity fix, not a policy decision,
so it is unconditional.

That truncation drops some number of `test_trial` rows. `create` measures the
loss (`events_truncation_stats`) and, in `run_create_events`, writes it next to
each `_events.tsv` as an `_events.json` sidecar:

```json
{"NTestTrialsExpected": 40, "NTestTrialsRetained": 12, "FractionTestTrialsDropped": 0.7}
```

**This package makes no exclusion decision from that number.** Deciding
whether a given `FractionTestTrialsDropped` is small enough to salvage the run
or large enough to exclude it (the monolith used a >50% threshold) is
`network_qa`'s job -- it is the consumer of this sidecar.

## Install

Requires Python >=3.11. On a compute node (never the login node on a shared
HPC cluster):

```bash
uv sync
```

Dependencies: `numpy`, `pandas` (plus `nibabel`, used only by `trim.py`, which
must be available in the environment you run trimming in).

## Pipeline steps

| Step | Module | Role |
|------|--------|------|
| `reconcile` | `network_events.reconcile` | Read-only: match BIDS BOLD scans to raw behavioral CSVs -> TSV manifest for human review |
| `migrate` | `network_events.migrate` | Copy in-scanner behavioral (per reviewed manifest) into BIDS `sourcedata/in_scanner_behavior/` |
| `migrate-archive` | `network_events.migrate` | Copy out-of-scanner practice/pretouch behavioral into `sourcedata/out_scanner_behavior/` |
| `migrate-survey` | `network_events.migrate` | Copy prescan/demographics survey data into `sourcedata/survey_data/` |
| `create` | `network_events.create` | Generate BIDS `_events.tsv` files from `sourcedata` behavioral CSVs |
| `qc` | `network_events.qc` | Compute behavioral QC metrics, flag task-specific exclusion criteria, detect RT-tail-cutoff trim candidates |
| `trim` | `network_events.trim` | Trim BOLD NIfTIs to match a behavioral cutoff detected by QC |

Each step is invocable individually via the `network-events` CLI, or as a
single orchestrated run via `network-events run`, which enforces a
**manifest review gate**: without a reviewed manifest it runs `reconcile`
only and stops, printing the manifest path for human review; re-run with
`--manifest <reviewed.tsv>` to proceed through migrate (in-scanner) ->
out-of-scanner -> create -> qc -> trim. (`run` also migrates survey data when
`--survey-root` is given; every migration step is separately invocable below.)

```bash
# Step 1: reconcile only, review the manifest it writes
network-events run --behavioral-dir <raw> --bids-dir <BIDS>

# Step 2: after reviewing/resolving 'pending' rows in the manifest
network-events run --behavioral-dir <raw> --bids-dir <BIDS> \
  --manifest <BIDS>/reconciliation_manifest.tsv [--survey-root <survey_data>]
```

Individual subcommands:

```bash
network-events reconcile --bids-dir <BIDS> --raw-dir <raw> \
  [--scan-notes SCAN-NOTES.md] --output manifest.tsv

network-events migrate --manifest manifest.tsv --output-dir <BIDS>/sourcedata [--strict]

network-events migrate-archive --raw-dir <raw> --output-dir <BIDS>/sourcedata \
  --manifest manifest.tsv [--manifest other_manifest.tsv ...]

network-events migrate-survey --survey-root <survey_data> --output-dir <BIDS>/sourcedata \
  --manifest manifest.tsv [--manifest other_manifest.tsv ...]

network-events create --sourcedata <BIDS>/sourcedata --bids-dir <BIDS>

network-events qc --sourcedata <BIDS>/sourcedata --bids-dir <BIDS>

network-events trim --bids-dir <BIDS>
```

## `datalad run` recipes

All commands are pure/idempotent given the same inputs, so an operator can
wrap them in `datalad run` for full provenance capture:

```bash
datalad run -m "network_events: migrate in-scanner behavioral" \
  --output 'sourcedata/in_scanner_behavior/**' \
  --output 'sourcedata/migration_report.json' \
  network-events migrate --manifest manifest.tsv --output-dir sourcedata --strict

datalad run -m "network_events: migrate out-of-scanner behavioral" \
  --output 'sourcedata/out_scanner_behavior/**' \
  --output 'sourcedata/archive_migration_report.json' \
  network-events migrate-archive --raw-dir <raw> --output-dir sourcedata --manifest manifest.tsv

datalad run -m "network_events: migrate survey data" \
  --output 'sourcedata/survey_data/**' \
  --output 'sourcedata/survey_migration_report.json' \
  network-events migrate-survey --survey-root <survey_data> --output-dir sourcedata --manifest manifest.tsv

datalad run -m "network_events: generate events" \
  --input 'sourcedata/in_scanner_behavior/**' \
  --output 'sub-*/ses-*/func/*_events.tsv' \
  --output 'sub-*/ses-*/func/*_events.json' \
  network-events create --sourcedata sourcedata --bids-dir .

datalad run -m "network_events: behavioral QC" \
  --input 'sourcedata/in_scanner_behavior/**' \
  --output 'sourcedata/behavioral_qc/trim_list.json' \
  network-events qc --sourcedata sourcedata --bids-dir .

datalad run -m "network_events: trim BOLD to behavioral cutoff" \
  --input 'sourcedata/behavioral_qc/trim_list.json' \
  --input 'sub-*/ses-*/func/*_bold.nii.gz' \
  --output 'derivatives/trimmed/sub-*/ses-*/func/*_desc-trimmed_bold.nii.gz' \
  network-events trim --bids-dir .
```

## Testing

```bash
PYTHONPATH=src python -m pytest tests/ -v
```
