"""Audit canonical behavioral identities and create their BIDS events."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from network_events.create import create_events
from network_events.identity import AuditResult, audit_dataset


def _audit_payload(result: AuditResult) -> dict[str, object]:
    return {
        "pairs": [
            {
                "subject": identity.subject,
                "session": identity.session,
                "task": identity.task,
                "run": identity.run,
                "behavior_file": str(behavior_file),
            }
            for identity, behavior_file in result.pairs
        ],
        "exceptions": [
            {
                "subject": exception.identity.subject,
                "session": exception.identity.session,
                "task": exception.identity.task,
                "run": exception.identity.run,
                "reason": exception.reason,
                "detail": exception.detail,
            }
            for exception in result.exceptions
        ],
        "errors": list(result.errors),
    }


def _print_payload(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
    temporary_path.replace(path)


def _audit(args: argparse.Namespace) -> int:
    result = audit_dataset(args.bids_dir, args.behavioral_dir)
    payload = _audit_payload(result)
    _print_payload(payload)
    if args.json is not None:
        _write_json(args.json, payload)
    return 0 if args.behavioral_dir.is_dir() and not result.errors else 2


def _create(args: argparse.Namespace) -> int:
    result = audit_dataset(args.bids_dir, args.behavioral_dir)
    payload = _audit_payload(result)
    if not args.behavioral_dir.is_dir() or result.errors:
        _print_payload({"audit": payload, "created": 0, "failed": 0})
        return 2

    conversion_results = create_events(args.bids_dir, result.pairs)
    created = sum(item.status == "created" for item in conversion_results)
    failed = sum(item.status == "failed" for item in conversion_results)
    _print_payload({"audit": payload, "created": created, "failed": failed})
    return 0 if created + failed == len(result.pairs) else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="network-events", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--bids-dir", type=Path, required=True)
    audit_parser.add_argument("--behavioral-dir", type=Path, required=True)
    audit_parser.add_argument("--json", type=Path)
    audit_parser.set_defaults(handler=_audit)

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--bids-dir", type=Path, required=True)
    create_parser.add_argument("--behavioral-dir", type=Path, required=True)
    create_parser.set_defaults(handler=_create)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
