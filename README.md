# network_events

`network-events` converts the finalized in-scanner behavioral CSVs into BIDS
`_events.tsv` files. It does not reorganize or remap raw behavior.

## Setup

```bash
uv sync
```

## Input

The behavioral directory must already match the BIDS scans one-to-one:

```text
sourcedata/behavioral/in_scanner/
  behavioral_exceptions.tsv
  sub-s01/ses-01/beh/sub-s01_ses-01_task-nBack_run-1_beh.csv
```

Subject, session, task, and run entities must match the corresponding BOLD file.
Reviewed scans without recoverable behavior belong in `behavioral_exceptions.tsv`.

## Create events

Audit identities without writing events:

```bash
network-events audit \
  --bids-dir /path/to/bids \
  --behavioral-dir /path/to/bids/sourcedata/behavioral/in_scanner
```

Use `--subject sub-s03` to audit a one-subject pilot against the full canonical
behavioral source.

Create all audited events files:

```bash
network-events create \
  --bids-dir /path/to/bids \
  --behavioral-dir /path/to/bids/sourcedata/behavioral/in_scanner
```

Events are written beside their BOLD files. Conversion errors and truncation evidence
are written under `sourcedata/events_qc/`. Event onsets use the discarded-volume count
and repetition time recorded in each BOLD sidecar and are clipped to the acquired scan.

## Development

```bash
uv lock --check
uv run pytest -q
uv build
git diff --check
```
