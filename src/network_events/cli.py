"""network-events CLI: subcommands mirror the behavioral pipeline steps.

All subcommands are pure/idempotent so an operator can wrap them in `datalad run`.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from network_events import migrate as _migrate_mod
from network_events.run import subjects_in
from network_events.create import run_create_events
from network_events.qc import run_qc
from network_events.trim import run_trim
from network_events.run import run as _orchestrate




def _migrate_archive(a):
    subjects = subjects_in(Path(a.output_dir))
    copied = _migrate_mod.migrate_out_scanner(raw_dir=a.raw_dir,
                                              output_dir=a.output_dir, subjects=subjects)
    payload = {"subjects": sorted(subjects), "out_scanner_files": copied}
    _migrate_mod._write_migration_report(payload, a.output_dir, "archive_migration_report.json")

def _migrate_survey(a):
    subjects = subjects_in(Path(a.output_dir))
    copied = _migrate_mod.migrate_survey(survey_root=a.survey_root,
                                        output_dir=a.output_dir, subjects=subjects)
    payload = {"subjects": sorted(subjects), "survey_files": copied}
    _migrate_mod._write_migration_report(payload, a.output_dir, "survey_migration_report.json")

def _in_scanner(sourcedata):
    """Resolve the dir holding sub-*/ses-*/beh CSVs. In-scanner behavioral
    migrates to <sourcedata>/in_scanner_behavior/, so prefer that when present;
    fall back to the given path (already the in_scanner dir)."""
    sd = Path(sourcedata)
    cand = sd / "in_scanner_behavior"
    return cand if cand.is_dir() else sd

def _create(a):
    run_create_events(behavioral_dir=_in_scanner(a.sourcedata), bids_dir=Path(a.bids_dir))

def _qc(a):
    run_qc(behavioral_dir=_in_scanner(a.sourcedata), bids_dir=Path(a.bids_dir))

def _trim(a):
    run_trim(bids_dir=Path(a.bids_dir))

def _run(a):
    _orchestrate(behavioral_dir=a.behavioral_dir, bids_dir=a.bids_dir,
                 survey_root=a.survey_root)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="network-events", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("migrate-archive"); p.add_argument("--raw-dir", required=True)
    p.add_argument("--output-dir", required=True)
    p.set_defaults(func=_migrate_archive)

    p = sub.add_parser("migrate-survey"); p.add_argument("--survey-root", required=True)
    p.add_argument("--output-dir", required=True)
    p.set_defaults(func=_migrate_survey)

    p = sub.add_parser("create"); p.add_argument("--sourcedata", required=True)
    p.add_argument("--bids-dir", required=True); p.set_defaults(func=_create)

    p = sub.add_parser("qc"); p.add_argument("--sourcedata", required=True)
    p.add_argument("--bids-dir", required=True); p.set_defaults(func=_qc)

    p = sub.add_parser("trim"); p.add_argument("--bids-dir", required=True); p.set_defaults(func=_trim)

    p = sub.add_parser("run"); p.add_argument("--behavioral-dir", required=True)
    p.add_argument("--bids-dir", required=True)
    p.add_argument("--survey-root", default=None); p.set_defaults(func=_run)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
