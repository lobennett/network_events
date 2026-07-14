"""network-events CLI: subcommands mirror the behavioral pipeline steps.

All subcommands are pure/idempotent so an operator can wrap them in `datalad run`.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from network_events import reconcile as _reconcile_mod
from network_events import migrate as _migrate_mod
from network_events.create import run_create_events
from network_events.qc import run_qc
from network_events.trim import run_trim
from network_events.run import run as _orchestrate


def _reconcile(a):
    rows = _reconcile_mod.reconcile(bids_dir=a.bids_dir, raw_dir=a.raw_dir,
                                     scan_notes_path=a.scan_notes)
    _reconcile_mod.write_manifest_tsv(rows, a.output)

def _migrate(a):
    _migrate_mod.migrate_from_manifest(manifest_path=a.manifest,
                                       output_dir=a.output_dir, strict=a.strict)

def _create(a):
    run_create_events(behavioral_dir=Path(a.sourcedata), bids_dir=Path(a.bids_dir))

def _qc(a):
    run_qc(behavioral_dir=Path(a.sourcedata), bids_dir=Path(a.bids_dir))

def _trim(a):
    run_trim(bids_dir=Path(a.bids_dir))

def _run(a):
    _orchestrate(behavioral_dir=a.behavioral_dir, bids_dir=a.bids_dir,
                 manifest=a.manifest, survey_root=a.survey_root)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="network-events", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("reconcile"); p.add_argument("--bids-dir", required=True)
    p.add_argument("--raw-dir", required=True); p.add_argument("--scan-notes", default=None)
    p.add_argument("--output", required=True); p.set_defaults(func=_reconcile)

    p = sub.add_parser("migrate"); p.add_argument("--manifest", required=True)
    p.add_argument("--output-dir", required=True); p.add_argument("--strict", action="store_true")
    p.set_defaults(func=_migrate)

    p = sub.add_parser("create"); p.add_argument("--sourcedata", required=True)
    p.add_argument("--bids-dir", required=True); p.set_defaults(func=_create)

    p = sub.add_parser("qc"); p.add_argument("--sourcedata", required=True)
    p.add_argument("--bids-dir", required=True); p.set_defaults(func=_qc)

    p = sub.add_parser("trim"); p.add_argument("--bids-dir", required=True); p.set_defaults(func=_trim)

    p = sub.add_parser("run"); p.add_argument("--behavioral-dir", required=True)
    p.add_argument("--bids-dir", required=True); p.add_argument("--manifest", default=None)
    p.add_argument("--survey-root", default=None); p.set_defaults(func=_run)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
