"""Exact identities for canonical behavioral files and logical BOLD runs."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


_BEHAVIOR_RE = re.compile(
    r"^(?P<subject>sub-[A-Za-z0-9]+)_(?P<session>ses-[A-Za-z0-9]+)_task-(?P<task>[A-Za-z0-9]+)_run-(?P<run>[A-Za-z0-9]+)_beh\.csv$"
)
_BOLD_RE = re.compile(
    r"^(?P<subject>sub-[A-Za-z0-9]+)_(?P<session>ses-[A-Za-z0-9]+)_task-(?P<task>[A-Za-z0-9]+)_run-(?P<run>[A-Za-z0-9]+)(?:_echo-(?P<echo>[0-9]+))?_bold\.nii(?:\.gz)?$"
)
_BOLD_PREFIX_RE = re.compile(
    r"^(?P<subject>sub-[A-Za-z0-9]+)_(?P<session>ses-[A-Za-z0-9]+)_task-(?P<task>[A-Za-z0-9]+)_run-(?P<run>[A-Za-z0-9]+)_"
)
_EXCEPTION_COLUMNS = (
    "subject", "session", "task", "run", "reason", "detail", "reviewed_by", "reviewed_at"
)
_LABEL_RE = re.compile(r"^[A-Za-z0-9]+$")


@dataclass(frozen=True, order=True)
class RunIdentity:
    subject: str
    session: str
    task: str
    run: str

    def display(self) -> str:
        return f"{self.subject}/{self.session}/task-{self.task}/run-{self.run}"


@dataclass(frozen=True)
class BehaviorException:
    identity: RunIdentity
    reason: str
    detail: str


@dataclass(frozen=True)
class BoldGroup:
    """Physical images belonging to one unambiguous logical acquisition."""

    identity: RunIdentity
    files: tuple[Path, ...]


@dataclass(frozen=True)
class AuditResult:
    pairs: tuple[tuple[RunIdentity, Path], ...]
    exceptions: tuple[BehaviorException, ...]
    errors: tuple[str, ...]
    bold_groups: tuple[BoldGroup, ...] = ()


def _identity(match: re.Match[str]) -> RunIdentity:
    return RunIdentity(*(match.group(key) for key in ("subject", "session", "task", "run")))


def _read_exceptions(path: Path) -> tuple[dict[RunIdentity, BehaviorException], list[str]]:
    if not path.exists():
        return {}, []
    errors: list[str] = []
    exceptions: dict[RunIdentity, BehaviorException] = {}
    duplicates: set[RunIdentity] = set()
    try:
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            columns = tuple(reader.fieldnames or ())
            missing = [column for column in _EXCEPTION_COLUMNS if column not in columns]
            if missing:
                return {}, [f"{path}: missing required columns: {', '.join(missing)}"]
            for row_number, row in enumerate(reader, start=2):
                values = {column: (row.get(column) or "").strip() for column in _EXCEPTION_COLUMNS}
                identity_values = (values["subject"], values["session"], values["task"], values["run"])
                valid_identity = (
                    _LABEL_RE.fullmatch(values["subject"].removeprefix("sub-")) is not None
                    and values["subject"].startswith("sub-")
                    and _LABEL_RE.fullmatch(values["session"].removeprefix("ses-")) is not None
                    and values["session"].startswith("ses-")
                    and all(_LABEL_RE.fullmatch(value) for value in identity_values[2:])
                )
                if not all(values.values()) or not valid_identity:
                    errors.append(f"{path}:{row_number}: malformed exception row")
                    continue
                identity = RunIdentity(
                    values["subject"], values["session"], values["task"], values["run"]
                )
                if identity in exceptions:
                    errors.append(f"{identity.display()}: duplicate exception")
                    duplicates.add(identity)
                    continue
                exceptions[identity] = BehaviorException(
                    identity=identity, reason=values["reason"], detail=values["detail"]
                )
    except (OSError, csv.Error) as exc:
        errors.append(f"{path}: unreadable exceptions file: {exc}")
    for identity in duplicates:
        exceptions.pop(identity, None)
    return exceptions, errors


def discover_bold_groups(bids_dir: Path) -> tuple[tuple[BoldGroup, ...], tuple[str, ...]]:
    """Reject identity collisions before collapsing the expected echo variation."""
    bids_dir = Path(bids_dir)
    if not bids_dir.is_dir():
        return (), (f"{bids_dir}: BIDS root is not an existing directory",)
    files: dict[RunIdentity, list[Path]] = {}
    echoes: dict[RunIdentity, set[int | None]] = {}
    unusable: set[RunIdentity] = set()
    errors: list[str] = []
    for path in sorted(bids_dir.glob("sub-*/ses-*/func/*_bold.nii*")):
        match = _BOLD_RE.fullmatch(path.name)
        if match is None:
            errors.append(f"{path}: unparseable BOLD file (only echo variation is supported)")
            prefix = _BOLD_PREFIX_RE.match(path.name)
            if prefix:
                unusable.add(_identity(prefix))
            continue
        identity = _identity(match)
        files.setdefault(identity, []).append(path)
        expected = (identity.subject, identity.session, "func", path.name)
        if path.relative_to(bids_dir).parts != expected:
            errors.append(f"{path}: noncanonical BOLD path")
            unusable.add(identity)
        echo = int(match.group("echo")) if match.group("echo") else None
        observed = echoes.setdefault(identity, set())
        if echo == 0 or echo in observed or (observed and (echo is None or None in observed)):
            errors.append(f"{identity.display()}: ambiguous duplicate physical BOLD acquisition: {path}")
            unusable.add(identity)
        observed.add(echo)
    groups = tuple(
        BoldGroup(identity, tuple(files[identity]))
        for identity in sorted(files) if identity not in unusable
    )
    return groups, tuple(sorted(errors))


def audit_dataset(bids_dir: Path, behavioral_dir: Path) -> AuditResult:
    """Require one canonical behavior file or reviewed exception per non-rest BOLD."""
    bids_dir, behavioral_dir = Path(bids_dir), Path(behavioral_dir)
    errors = [
        f"{root}: {label} root is not an existing directory"
        for root, label in ((bids_dir, "BIDS"), (behavioral_dir, "behavioral"))
        if not root.is_dir()
    ]
    if errors:
        return AuditResult(pairs=(), exceptions=(), errors=tuple(errors))
    behavior_files: dict[RunIdentity, Path] = {}
    seen_behavior: set[RunIdentity] = set()
    unusable_behavior: set[RunIdentity] = set()
    for csv_path in sorted(behavioral_dir.rglob("*.csv")):
        match = _BEHAVIOR_RE.fullmatch(csv_path.name)
        if match is None:
            errors.append(f"{csv_path}: unparseable behavior file")
            continue
        identity = _identity(match)
        if identity in seen_behavior:
            errors.append(f"{identity.display()}: duplicate behavior")
            unusable_behavior.add(identity)
        seen_behavior.add(identity)
        expected_parts = (identity.subject, identity.session, "beh", csv_path.name)
        if csv_path.relative_to(behavioral_dir).parts != expected_parts:
            errors.append(f"{csv_path}: noncanonical behavior path")
            unusable_behavior.add(identity)
            continue
        behavior_files[identity] = csv_path

    bold_groups, bold_errors = discover_bold_groups(bids_dir)
    errors.extend(bold_errors)
    bolds = {group.identity for group in bold_groups}

    exceptions, exception_errors = _read_exceptions(behavioral_dir / "behavioral_exceptions.tsv")
    errors.extend(exception_errors)
    non_rest_bolds = {identity for identity in bolds if identity.task != "rest"}

    for identity in sorted(behavior_files):
        if identity not in non_rest_bolds:
            errors.append(f"{identity.display()}: orphan behavior")
    for identity in sorted(exceptions):
        if identity not in non_rest_bolds:
            errors.append(f"{identity.display()}: orphan exception")
    for identity in sorted(non_rest_bolds):
        has_behavior = identity in behavior_files and identity not in unusable_behavior
        has_exception = identity in exceptions
        if has_behavior and has_exception:
            errors.append(f"{identity.display()}: both behavior and exception")
        elif not has_behavior and not has_exception:
            errors.append(f"{identity.display()}: missing behavior and exception")

    pairs = tuple(
        (identity, behavior_files[identity])
        for identity in sorted(non_rest_bolds)
        if identity in behavior_files
        and identity not in unusable_behavior
        and identity not in exceptions
    )
    reviewed = tuple(exceptions[identity] for identity in sorted(exceptions))
    return AuditResult(
        pairs=pairs, exceptions=reviewed, errors=tuple(sorted(errors)), bold_groups=bold_groups
    )
