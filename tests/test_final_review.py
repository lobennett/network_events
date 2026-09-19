"""Final-review regressions exercised through the shared audit and real writer."""
import json

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

from network_events.cli import main
from network_events.create import create_events
from network_events.identity import audit_dataset
from tests.helpers import audited_create, write_bold
from tests.test_conversion_results import (
    valid_behavior_pair, expected_events_path, read_tsv,
)
from tests.test_identity import dataset_with_bold, write_behavior


@pytest.mark.parametrize('root', ['bids', 'behavior'])
@pytest.mark.parametrize('kind', ['absent', 'file'])
@pytest.mark.parametrize('command', ['audit', 'create'])
def test_unavailable_roots_are_shared_audit_errors(tmp_path, capsys, root, kind, command):
    bids, behavior = tmp_path / 'bids', tmp_path / 'behavior'
    bids.mkdir()
    behavior.mkdir()
    bad = bids if root == 'bids' else behavior
    bad.rmdir()
    if kind == 'file':
        bad.write_text('not a directory')
    result = audit_dataset(bids, behavior)
    assert result.errors
    assert result.pairs == ()
    assert main([command, '--bids-dir', str(bids), '--behavioral-dir', str(behavior)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert (payload.get('audit') or payload)['errors']
    if root == 'bids' and kind == 'absent':
        assert not bids.exists()


@pytest.mark.parametrize('entity', ['subject', 'session'])
def test_bold_parent_must_match_filename(tmp_path, entity):
    bids, behavior = dataset_with_bold(tmp_path, task='nBack')
    write_behavior(behavior, 'sub-s01_ses-01_task-nBack_run-1_beh.csv')
    bold, = bids.glob('sub-*/ses-*/func/*nii.gz')
    wrong = bids / ('sub-s02' if entity == 'subject' else 'sub-s01') / (
        'ses-02' if entity == 'session' else 'ses-01') / 'func' / bold.name
    wrong.parent.mkdir(parents=True)
    bold.rename(wrong)
    audit = audit_dataset(bids, behavior)
    assert any('noncanonical BOLD path' in error for error in audit.errors)
    assert audit.pairs == ()


@pytest.mark.parametrize('variant', [
    '_bold.nii', '_acq-other_bold.nii.gz', '_part-phase_bold.nii.gz',
    '_echo-1_bold.nii.gz',
])
def test_ambiguous_physical_acquisitions_are_not_paired(tmp_path, variant):
    bids, behavior = dataset_with_bold(tmp_path, task='nBack')
    write_behavior(behavior, 'sub-s01_ses-01_task-nBack_run-1_beh.csv')
    func = bids / 'sub-s01/ses-01/func'
    (func / ('sub-s01_ses-01_task-nBack_run-1' + variant)).touch()
    audit = audit_dataset(bids, behavior)
    assert audit.errors
    assert audit.pairs == ()
    assert main(['create', '--bids-dir', str(bids), '--behavioral-dir', str(behavior)]) == 2
    assert not list(func.glob('*events.tsv'))


def test_duplicate_numeric_echo_labels_are_ambiguous(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task='nBack', echoes=(1,))
    write_behavior(behavior, 'sub-s01_ses-01_task-nBack_run-1_beh.csv')
    (bids / 'sub-s01/ses-01/func/sub-s01_ses-01_task-nBack_run-1_echo-01_bold.nii.gz').touch()
    assert audit_dataset(bids, behavior).pairs == ()
    assert audit_dataset(bids, behavior).errors


def test_audit_retains_expected_echo_files(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task='nBack', echoes=(1, 2, 3))
    write_behavior(behavior, 'sub-s01_ses-01_task-nBack_run-1_beh.csv')
    audit = audit_dataset(bids, behavior)
    assert audit.errors == ()
    assert len(audit.bold_groups) == 1
    assert audit.bold_groups[0].identity == audit.pairs[0][0]
    assert audit.bold_groups[0].files == tuple(sorted(bids.glob('sub-*/ses-*/func/*nii.gz')))


@pytest.mark.parametrize('damage', [
    'missing_json', 'broken_json', 'list_json', 'missing_discarded', 'negative_discarded',
    'fractional_discarded', 'bool_discarded', 'missing_tr', 'zero_tr', 'negative_tr',
    'nan_tr', 'infinite_tr', 'string_tr', 'bool_tr', 'unreadable_bold', 'three_dimensional',
    'zero_header_tr', 'nan_header_tr', 'header_sidecar_tr_conflict', 'missing_bold',
    'truncated_bold',
])
def test_missing_or_invalid_timing_is_recorded_failure(tmp_path, damage):
    bids, pair = valid_behavior_pair(tmp_path)
    audit = audit_dataset(bids, bids / 'sourcedata/behavioral')
    assert audit.errors == ()
    bold, = bids.glob('sub-*/ses-*/func/*nii.gz')
    sidecar = bold.with_name(bold.name.removesuffix('.nii.gz') + '.json')
    meta = json.loads(sidecar.read_text())
    if damage == 'missing_json':
        sidecar.unlink()
    elif damage == 'broken_json':
        sidecar.write_text('{')
    elif damage == 'list_json':
        sidecar.write_text('[]')
    elif damage == 'missing_bold':
        bold.unlink()  # Evidence disappearing after a successful audit also fails.
    elif damage == 'unreadable_bold':
        bold.write_text('unreadable')
    elif damage == 'truncated_bold':
        bold.write_bytes(bold.read_bytes()[:40])
    elif damage in ('three_dimensional', 'zero_header_tr', 'nan_header_tr'):
        shape = (2, 2, 2) if damage == 'three_dimensional' else (2, 2, 2, 100)
        img = nib.Nifti1Image(np.zeros(shape, dtype=np.int16), np.eye(4))
        if len(shape) == 4:
            img.header['pixdim'][4] = 0 if damage == 'zero_header_tr' else np.nan
        nib.save(img, bold)
    else:
        key = 'NumberOfVolumesDiscardedByUser' if damage.endswith('discarded') else 'RepetitionTime'
        value = {
            'negative_discarded': -1, 'fractional_discarded': 1.5, 'bool_discarded': True,
            'zero_tr': 0, 'negative_tr': -1, 'nan_tr': float('nan'),
            'infinite_tr': float('inf'), 'string_tr': '1.49', 'bool_tr': True,
            'header_sidecar_tr_conflict': 2.0,
        }.get(damage)
        if damage.startswith('missing_'):
            meta.pop(key)
        else:
            meta[key] = value
        sidecar.write_text(json.dumps(meta))
    events = expected_events_path(bids, pair[0])
    events.write_text('stale events')
    result, = create_events(bids, audit.pairs)
    assert result.status == 'failed'
    assert result.events_file is None and result.qc_file is None
    assert not events.exists()
    rows = read_tsv(bids / 'sourcedata/events_qc/conversion_errors.tsv')
    assert len(rows) == 1
    assert rows[0]['exception_class'] == 'TimingEvidenceError'
    assert rows[0]['source_path'] == str(pair[1])
    assert rows[0]['message']


@pytest.mark.parametrize('extension', ['.nii', '.nii.gz'])
@pytest.mark.parametrize('discarded', [0, 7])
def test_valid_timing_and_extensions_through_cli(tmp_path, capsys, extension, discarded):
    bids, pair = valid_behavior_pair(tmp_path)
    bold, = bids.glob('sub-*/ses-*/func/*nii.gz')
    bold.unlink()
    write_bold(bold.with_name(bold.name.removesuffix('.nii.gz') + extension),
               n_volumes=40, discarded=discarded)
    assert main(['create', '--bids-dir', str(bids), '--behavioral-dir',
                 str(bids / 'sourcedata/behavioral')]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['created'] == 1 and payload['failed'] == 0
    events = pd.read_csv(expected_events_path(bids, pair[0]), sep='\t')
    if discarded:
        assert events['onset'].tolist() == pytest.approx([20, 23, 26])
    else:
        assert events['onset'].tolist() == pytest.approx([30.43, 33.43, 36.43])
    qc = json.loads(next((bids / 'sourcedata/events_qc').rglob('*truncation.json')).read_text())
    assert qc['ScanDurationSeconds'] == pytest.approx(59.6)
    assert read_tsv(bids / 'sourcedata/events_qc/conversion_errors.tsv') == []


@pytest.mark.parametrize('conflict', ['none', 'discarded', 'tr', 'volumes', 'missing_json', 'broken_bold'])
def test_echo_timing_must_be_complete_and_consistent(tmp_path, conflict):
    bids, pair = valid_behavior_pair(tmp_path)
    bold, = bids.glob('sub-*/ses-*/func/*nii.gz')
    bold.unlink()
    for echo in (1, 2, 3):
        path = bold.with_name(bold.name.replace('_bold', f'_echo-{echo}_bold'))
        write_bold(path,
                   n_volumes=99 if echo == 3 and conflict == 'volumes' else 100,
                   tr=2 if echo == 3 and conflict == 'tr' else 1.49,
                   discarded=0 if echo == 3 and conflict == 'discarded' else 7)
        if echo == 3 and conflict == 'missing_json':
            path.with_name(path.name.removesuffix('.nii.gz') + '.json').unlink()
        if echo == 3 and conflict == 'broken_bold':
            path.write_text('broken')
    result, = audited_create(bids)
    assert result.status == ('created' if conflict == 'none' else 'failed')
    assert expected_events_path(bids, pair[0]).exists() == (conflict == 'none')


def test_cli_accounts_for_timing_failures(tmp_path, capsys):
    bids, pair = valid_behavior_pair(tmp_path)
    next(bids.glob('sub-*/ses-*/func/*bold.json')).unlink()
    assert main(['create', '--bids-dir', str(bids), '--behavioral-dir',
                 str(bids / 'sourcedata/behavioral')]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['created'] == 0 and payload['failed'] == 1
    assert not expected_events_path(bids, pair[0]).exists()


def test_legacy_writer_and_inferred_discovery_are_removed():
    import network_events.create as module
    for name in ('run_create_events', 'group_csvs_by_task', 'discover_nifti_tasks', 'create_empty_events_df'):
        assert not hasattr(module, name)


def test_missing_run_label_is_never_inferred(tmp_path):
    bids, behavior = dataset_with_bold(tmp_path, task='nBack')
    write_behavior(behavior, 'sub-s01_ses-01_task-nBack_beh.csv')
    result = audit_dataset(bids, behavior)
    assert result.pairs == ()
    assert any('unparseable behavior' in error for error in result.errors)


def test_valid_header_with_truncated_payload_fails(tmp_path):
    bids, pair = valid_behavior_pair(tmp_path)
    compressed, = bids.glob('sub-*/ses-*/func/*nii.gz')
    compressed.unlink()
    bold = write_bold(compressed.with_suffix(''))
    with bold.open('r+b') as stream:
        stream.truncate(400)  # Keep the NIfTI header, remove most voxel data.
    result, = audited_create(bids)
    assert result.status == 'failed'
    assert 'TimingEvidenceError' in result.error
    assert not expected_events_path(bids, pair[0]).exists()


def test_mixed_results_and_repaired_rerun_preserve_error_table_contract(tmp_path):
    bids, pair = valid_behavior_pair(tmp_path)
    behavior = bids / 'sourcedata/behavioral'
    second = pair[1].with_name(pair[1].name.replace('run-1', 'run-2'))
    second.write_bytes(pair[1].read_bytes())
    first_bold, = bids.glob('sub-*/ses-*/func/*nii.gz')
    second_bold = write_bold(first_bold.with_name(first_bold.name.replace('run-1', 'run-2')))
    sidecar = second_bold.with_name(second_bold.name.removesuffix('.nii.gz') + '.json')
    sidecar.unlink()
    results = audited_create(bids, behavior)
    assert [item.status for item in results] == ['created', 'failed']
    rows = read_tsv(bids / 'sourcedata/events_qc/conversion_errors.tsv')
    assert len(rows) == 1 and rows[0]['run'] == '2'
    write_bold(second_bold)
    assert all(item.status == 'created' for item in audited_create(bids, behavior))
    assert read_tsv(bids / 'sourcedata/events_qc/conversion_errors.tsv') == []
