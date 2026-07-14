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
| `migrate` | `network_events.migrate` | Copy in-scanner behavioral (per reviewed manifest), out-of-scanner practice/pretouch, and survey data into BIDS `sourcedata/` |
| `create` | `network_events.create` | Generate BIDS `_events.tsv` files from `sourcedata` behavioral CSVs |
| `qc` | `network_events.qc` | Compute behavioral QC metrics, flag task-specific exclusion criteria, detect RT-tail-cutoff trim candidates |
| `trim` | `network_events.trim` | Trim BOLD NIfTIs to match a behavioral cutoff detected by QC |

Each step is invocable individually via the `network-events` CLI, or as a
single orchestrated run via `network-events run`, which enforces a
**manifest review gate**: without a reviewed manifest it runs `reconcile`
only and stops, printing the manifest path for human review; re-run with
`--manifest <reviewed.tsv>` to proceed through migrate -> create -> qc -> trim.

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

network-events create --sourcedata <BIDS>/sourcedata --bids-dir <BIDS>

network-events qc --sourcedata <BIDS>/sourcedata --bids-dir <BIDS>

network-events trim --bids-dir <BIDS>
```

## `datalad run` recipes

All commands are pure/idempotent given the same inputs, so an operator can
wrap them in `datalad run` for full provenance capture:

```bash
datalad run -m "network_events: generate events" \
  --input 'sourcedata/in_scanner_behavior/**' \
  --output 'sub-*/ses-*/func/*_events.tsv' \
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
