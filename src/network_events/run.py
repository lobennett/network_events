"""Orchestrate the behavioral half: cleaned sourcedata -> events + QC + trim.

Pure + idempotent so an operator can wrap each invocation in `datalad run`.

The in-scanner behavioral tree arrives already reconciled: `network_fmri ingest-beh` copies
it from the canonical dataset at `$OAK/.../behavioral_data/canonical` into
`sourcedata/<sub>/<ses>/beh/<sub>_<ses>_task-<T>_run-<N>_beh.csv`, one CSV per BOLD run.
Session alignment and run assignment are settled there, which removes the reconciliation
manifest and its review gate entirely.
"""
from __future__ import annotations

from pathlib import Path

from network_events.create import run_create_events
from network_events.migrate import migrate_out_scanner, migrate_survey
from network_events.qc import run_qc
from network_events.trim import run_trim


def subjects_in(sourcedata: Path) -> set[str]:
    """Subject labels present in the cleaned in-scanner tree."""
    return {p.name.replace("sub-", "") for p in sourcedata.glob("sub-*") if p.is_dir()}


def run(behavioral_dir, bids_dir, survey_root=None) -> None:
    """Generate events for every cleaned in-scanner CSV, then QC and trim."""
    behavioral_dir, bids_dir = Path(behavioral_dir), Path(bids_dir)
    sourcedata = bids_dir / "sourcedata"

    subjects = subjects_in(sourcedata)
    if not subjects:
        raise SystemExit(
            f"no sub-* directories in {sourcedata}: run `network_fmri ingest-beh` first"
        )

    migrate_out_scanner(raw_dir=behavioral_dir, output_dir=sourcedata, subjects=subjects)
    if survey_root is not None:
        migrate_survey(survey_root=Path(survey_root), output_dir=sourcedata, subjects=subjects)

    run_create_events(behavioral_dir=sourcedata, bids_dir=bids_dir)
    run_qc(behavioral_dir=sourcedata, bids_dir=bids_dir)
    run_trim(bids_dir=bids_dir)
