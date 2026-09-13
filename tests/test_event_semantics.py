"""Synthetic jsPsych exports through canonical CSV -> BIDS TSV + QC sidecar.

Rows use the package's raw column contract: time_elapsed is block-end time,
RT -1 is no response, and correct_response -1 is a no-go target. No participant
data are used. The inherited feedback conditions exercise the recovered defect.
"""
import json

import numpy as np
import pandas as pd
import pytest

from network_events.cli import main
from tests.test_scanlength import _write_bold


def _write_go_nogo_csv(path, *, metadata_gap=False, inherited_conditions=True):
    exp_id = "go_nogo_single_task_network__fmri"
    rows = [{
        "exp_id": exp_id, "trial_id": "fmri_trigger_initial",
        "time_elapsed": 5000, "block_duration": 100, "stim_duration": 0,
        "rt": 0, "key_press": -1, "correct_response": -1,
        "go_nogo_condition": np.nan, "stimulus": np.nan,
    }]
    elapsed = 5000
    for trial_id, duration, condition, key, correct, rt, stimulus in [
        ("update_correct_response", 12000, None, -1, -1, -1, "+"),
        ("test_trial", 1000, "go", 37, 37, 450, "X"),
        ("feedback_block", 6000, "go", -1, -1, -1, "You completed a block."),
        ("test_trial", 1000, "go", -1, 37, -1, "X"),
        ("feedback_block", 6000, "nogo", -1, -1, -1, "Your accuracy was low."),
        ("test_trial", 1000, "nogo", -1, -1, -1, "Y"),
        ("feedback_block", 6000, "nogo", 37, -1, 500, "Please respond more slowly."),
        ("test_trial", 1000, "nogo", 37, -1, 500, "Y"),
        ("update_correct_response", 1000, "go", -1, -1, -1, "+"),
        ("test_trial", 1000, "go", 37, 39, 600, "X"),
        ("feedback_block", 6000, None, -1, -1, -1, "You completed the task."),
    ]:
        elapsed += duration
        rows.append({
            "exp_id": exp_id, "trial_id": trial_id, "time_elapsed": elapsed,
            "block_duration": duration, "stim_duration": duration, "rt": rt,
            "key_press": key, "correct_response": correct,
            "go_nogo_condition": condition if inherited_conditions or trial_id == "test_trial" else None,
            "stimulus": stimulus,
        })
    if metadata_gap:
        # An untimed setup row is removed by get_neg_rt_correction, leaving
        # original CSV indices intact for feedback matching.
        rows.insert(0, {"exp_id": exp_id, "trial_id": "design_setup"})
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _canonical_run(tmp_path, *, task="goNogo", sub="sub-synthetic", ses="ses-01", run=1,
                   n_volumes=100, tr=1.49, discarded=7):
    stem = f"{sub}_{ses}_task-{task}_run-{run}"
    beh = tmp_path / "sourcedata" / sub / ses / "beh"
    beh.mkdir(parents=True, exist_ok=True)
    func = tmp_path / sub / ses / "func"
    func.mkdir(parents=True, exist_ok=True)
    _write_bold(func / f"{stem}_bold.nii.gz", n_volumes, tr=tr)
    (func / f"{stem}_bold.json").write_text(json.dumps({
        "RepetitionTime": tr, "NumberOfVolumesDiscardedByUser": discarded,
    }))
    qc = tmp_path / "sourcedata" / "events_qc" / sub / ses / f"{stem}_desc-truncation.json"
    return beh / f"{stem}_beh.csv", func / f"{stem}_events.tsv", qc


def _create(tmp_path):
    main(["create", "--sourcedata", str(tmp_path / "sourcedata"), "--bids-dir", str(tmp_path)])


@pytest.mark.parametrize("metadata_gap", [False, True])
@pytest.mark.parametrize("inherited_conditions", [False, True])
def test_go_nogo_classifies_only_true_trials_without_changing_timing(
    tmp_path, metadata_gap, inherited_conditions,
):
    raw, tsv, qc = _canonical_run(tmp_path)
    _write_go_nogo_csv(raw, metadata_gap=metadata_gap, inherited_conditions=inherited_conditions)
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t", keep_default_na=False)
    trials = events[events.trial_id == "test_trial"]
    assert trials.trial_type.tolist() == ["go", "go", "nogo_success", "nogo_failure", "go"]
    assert trials.acc.tolist() == [1, 0, 1, 0, 0]
    assert trials.response_time.tolist() == ["0.45", "n/a", "n/a", "0.5", "0.6"]
    assert trials.onset.tolist() == pytest.approx([1.57, 8.57, 15.57, 22.57, 24.57])
    assert trials.duration.tolist() == [1.0] * 5

    nontrials = events[events.trial_id != "test_trial"]
    assert nontrials.trial_id.tolist() == [
        "break", "break_with_performance_feedback", "break_with_performance_feedback",
        "test_fixation", "break",
    ]
    assert nontrials.trial_type.tolist() == ["n/a"] * 5
    assert nontrials.onset.tolist() == pytest.approx([2.57, 9.57, 16.57, 23.57, 25.57])
    assert nontrials.duration.tolist() == [6.0, 6.0, 6.0, 1.0, 6.0]
    # Retain the source condition column as provenance; only the modeled
    # trial_type must stop claiming that breaks/fixations are task trials.
    assert nontrials.go_nogo_condition.tolist() == (
        ["go", "nogo", "nogo", "go", "n/a"] if inherited_conditions else ["n/a"] * 5
    )
    assert json.loads(qc.read_text()) == {
        "NTestTrialsExpected": 5, "NTestTrialsRetained": 5,
        "FractionTestTrialsDropped": 0.0,
        "ScanDurationSeconds": pytest.approx(149.0, abs=1e-4),
        "NScanTestTrialsDropped": 0, "FractionScanTestTrialsDropped": 0.0,
    }


@pytest.mark.parametrize("metadata_gap", [False, True])
def test_negative_rt_clock_reconstruction_uses_previous_retained_row(tmp_path, metadata_gap):
    raw, tsv, qc = _canonical_run(tmp_path)
    _write_go_nogo_csv(raw)
    source = pd.read_csv(raw)
    # The first trial logged a negative RT and a drifting block-end clock.
    # Duration-based reconstruction should recover the original endpoints.
    source.loc[2, "rt"] = -500
    source.loc[2:, "time_elapsed"] += 9000
    if metadata_gap:
        metadata = pd.DataFrame([{
            "exp_id": source.exp_id.iloc[0], "trial_id": "design_setup",
        }])
        source = pd.concat([source.iloc[:2], metadata, source.iloc[2:]], ignore_index=True)
    source.to_csv(raw, index=False)
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t")
    trials = events[events.trial_id == "test_trial"]
    assert trials.onset.tolist() == pytest.approx([1.57, 8.57, 15.57, 22.57, 24.57])
    assert trials.trial_type.tolist() == ["go", "go", "nogo_success", "nogo_failure", "go"]
    # This helper repairs the clock, not response measurements.
    assert trials.response_time.iloc[0] == -0.5
    assert json.loads(qc.read_text())["NTestTrialsRetained"] == 5


@pytest.mark.parametrize("missing_text", [None, 123, "absent_column"])
def test_feedback_without_text_keeps_events_and_plain_breaks(tmp_path, missing_text):
    raw, tsv, qc = _canonical_run(tmp_path)
    _write_go_nogo_csv(raw)
    source = pd.read_csv(raw)
    if missing_text == "absent_column":
        source = source.drop(columns="stimulus")
    else:
        source["stimulus"] = missing_text
    source.to_csv(raw, index=False)
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t")
    assert (events.trial_id == "test_trial").sum() == 5
    assert (events.trial_id == "break").sum() == 4
    assert not (events.trial_id == "break_with_performance_feedback").any()
    assert json.loads(qc.read_text())["NTestTrialsRetained"] == 5


def test_failed_rerun_cannot_retain_successful_trial_retention_sidecar(tmp_path):
    raw, tsv, qc = _canonical_run(tmp_path)
    _write_go_nogo_csv(raw)
    _create(tmp_path)
    original_events = tsv.read_bytes()
    original_qc = qc.read_bytes()
    _create(tmp_path)
    assert tsv.read_bytes() == original_events
    assert qc.read_bytes() == original_qc

    # Missing trigger is already a hard conversion failure. The CLI writes an
    # empty TSV, which must not be paired with the previous five-trial report.
    source = pd.read_csv(raw)
    source[source.trial_id != "fmri_trigger_initial"].to_csv(raw, index=False)
    _create(tmp_path)
    assert pd.read_csv(tsv, sep="\t").empty
    assert not qc.exists()

    _write_go_nogo_csv(raw)
    _create(tmp_path)
    assert tsv.read_bytes() == original_events
    assert qc.read_bytes() == original_qc


@pytest.mark.parametrize("discarded,expected_onsets", [(0, [0.0, 2.0]), (1, [0.0])])
def test_trial_at_scan_origin_is_retained(tmp_path, discarded, expected_onsets):
    raw, tsv, qc = _canonical_run(tmp_path, tr=2.0, discarded=discarded)
    _write_go_nogo_csv(raw)
    source = pd.read_csv(raw).iloc[[0, 2, 4]].copy()
    # Trigger at 5 s; two one-second stimuli begin at scanner times 0 and 2 s.
    source["time_elapsed"] = [5000, 6000, 8000]
    source.to_csv(raw, index=False)
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t")
    assert events.onset.tolist() == expected_onsets
    assert events.duration.tolist() == [1.0] * len(expected_onsets)
    assert json.loads(qc.read_text())["NTestTrialsExpected"] == len(expected_onsets)


@pytest.mark.parametrize("suffix", ["__fmri", ""])
def test_supported_shape_matching_cued_switch_alias_produces_same_conditions(tmp_path, suffix):
    raw, tsv, qc = _canonical_run(tmp_path, task="shapeMatchingWCuedTS")
    exp_id = f"shape_matching_with_cued_task_switching{suffix}"
    source = pd.DataFrame({
        "exp_id": [exp_id] * 4,
        "trial_id": ["fmri_trigger_initial", "cue", "test_trial", "feedback_block"],
        "time_elapsed": [5000, 17500, 18500, 24500],
        "block_duration": [100, 500, 1000, 6000],
        "stim_duration": [0, 500, 1000, 6000], "rt": [0, -1, 450, -1],
        "key_press": [-1, -1, 37, -1], "correct_response": [-1, -1, 37, -1],
        "cue": [None, "Parity", "Parity", None],
        "task_condition": [None, "stay", "stay", None],
        "cue_condition": [None, "switch", "switch", None],
        "shape_matching_condition": [None, None, "match", None],
        "probe": [None, None, "circle", None], "target": [None, None, "circle", None],
        "distractor": [None, None, "square", None],
        "stimulus": [None, "Parity", "circle", "You completed a block."],
    })
    source.to_csv(raw, index=False)
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t", keep_default_na=False)
    assert events.trial_id.tolist() == ["test_cue", "test_trial", "break"]
    assert events.trial_type.tolist() == ["tstay_cswitch", "tstay_cswitch", "n/a"]
    assert events.onset.tolist() == pytest.approx([1.57, 2.07, 3.07])
    assert events.correct_response.tolist() == ["n/a", "37", "-1"]
    assert events.shape_matching_condition.tolist() == ["n/a", "match", "n/a"]
    assert json.loads(qc.read_text())["NTestTrialsRetained"] == 1


@pytest.mark.parametrize("inherited_conditions", [False, True])
def test_stop_cleanup_does_not_classify_feedback_as_stop_outcomes(tmp_path, inherited_conditions):
    raw, tsv, qc = _canonical_run(tmp_path, task="stopSignal")
    _write_go_nogo_csv(raw, metadata_gap=True, inherited_conditions=inherited_conditions)
    source = pd.read_csv(raw).rename(columns={"go_nogo_condition": "stop_signal_condition"})
    source["exp_id"] = "stop_signal_single_task_network__fmri"
    source["stop_signal_condition"] = source.stop_signal_condition.replace("nogo", "stop")
    source["SS_delay"] = 250
    source["SS_duration"] = 500
    source["stop_acc"] = np.where(source.key_press == source.correct_response, 1, 0)
    source["go_acc"] = source.stop_acc
    source["stim"] = "arrow"
    # Raw stop exports label the inter-trial screen 'fixation'; only
    # _rename_cells turns it into the canonical 'test_fixation'.
    source["trial_id"] = source.trial_id.replace({
        "feedback_block": "practice-no-stop-feedback", "update_correct_response": "fixation",
    })
    source.to_csv(raw, index=False)
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t", keep_default_na=False)
    trials = events[events.trial_id == "test_trial"]
    assert trials.trial_type.tolist() == ["go", "go", "stop_success", "stop_failure", "go"]
    assert trials.onset.tolist() == pytest.approx([1.57, 8.57, 15.57, 22.57, 24.57])
    nontrials = events[events.trial_id != "test_trial"]
    assert nontrials.trial_id.tolist() == ["break", "break", "break", "test_fixation", "break"]
    # Breaks carry no condition and the fixation keeps its own named type,
    # whether or not the raw export left a go/stop label on those rows.
    assert nontrials.trial_type.tolist() == ["n/a", "n/a", "n/a", "fixation", "n/a"]
    assert nontrials.onset.tolist() == pytest.approx([2.57, 9.57, 16.57, 23.57, 25.57])
    assert nontrials.duration.tolist() == [6.0, 6.0, 6.0, 1.0, 6.0]
    # The raw condition column survives as provenance.
    assert nontrials.stop_signal_condition.tolist() == (
        ["go", "stop", "stop", "go", "n/a"] if inherited_conditions else ["n/a"] * 5
    )
    assert json.loads(qc.read_text())["NTestTrialsRetained"] == 5


def test_subject_session_and_run_use_their_own_scan_metadata(tmp_path):
    outputs = []
    for sub, ses, run, volumes, discarded, expected in [
        ("sub-alpha", "ses-01", 1, 10, 2, [8.0, 15.0]),
        ("sub-alpha", "ses-01", 2, 20, 0, [12.0, 19.0, 26.0, 33.0, 35.0]),
        ("sub-alpha", "ses-02", 1, 20, 3, [6.0, 13.0, 20.0, 27.0, 29.0]),
        ("sub-beta", "ses-01", 1, 10, 0, [12.0, 19.0]),
    ]:
        raw, tsv, qc = _canonical_run(
            tmp_path, sub=sub, ses=ses, run=run, n_volumes=volumes, tr=2.0, discarded=discarded,
        )
        _write_go_nogo_csv(raw)
        outputs.append((tsv, qc, expected, volumes * 2.0))
    _create(tmp_path)
    for tsv, qc, expected, scan_duration in outputs:
        events = pd.read_csv(tsv, sep="\t")
        assert events.loc[events.trial_id == "test_trial", "onset"].tolist() == expected
        stats = json.loads(qc.read_text())
        assert stats["ScanDurationSeconds"] == scan_duration
        assert stats["NScanTestTrialsDropped"] == 5 - len(expected)


def test_combined_clock_cut_and_scan_clip_report_separate_trial_costs(tmp_path):
    raw, tsv, qc = _canonical_run(tmp_path, n_volumes=5, tr=1.0, discarded=10)
    _write_go_nogo_csv(raw, metadata_gap=True)
    source = pd.read_csv(raw)
    third_trial = source.index[source.trial_id == "test_trial"][2]
    source.loc[third_trial:, "time_elapsed"] -= 8000
    source.to_csv(raw, index=False)
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t", keep_default_na=False)
    assert events.trial_id.tolist() == ["test_trial", "break"]
    assert events.onset.tolist() == [2.0, 3.0]
    # Onset clipping preserves the duration of the final retained event.
    assert events.duration.tolist() == [1.0, 6.0]
    assert json.loads(qc.read_text()) == {
        "NTestTrialsExpected": 5, "NTestTrialsRetained": 2,
        "FractionTestTrialsDropped": 0.6, "ScanDurationSeconds": 5.0,
        "NScanTestTrialsDropped": 1, "FractionScanTestTrialsDropped": 0.5,
    }


def test_negative_rt_without_a_clock_anchor_is_not_reconstructed(tmp_path):
    from network_events.create import create_events_df

    raw = _write_go_nogo_csv(tmp_path / "raw.csv", metadata_gap=True)
    source = pd.read_csv(raw)
    source.loc[source.trial_id == "fmri_trigger_initial", "rt"] = -500
    source.to_csv(raw, index=False)
    with pytest.raises(ValueError, match="preceding timed row"):
        create_events_df(raw, "goNogo")


@pytest.mark.parametrize("condition", [None, "unexpected"])
def test_go_nogo_unknown_trial_conditions_remain_unknown(tmp_path, condition):
    raw, tsv, qc = _canonical_run(tmp_path)
    _write_go_nogo_csv(raw)
    source = pd.read_csv(raw)
    source["go_nogo_condition"] = condition
    source.to_csv(raw, index=False)
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t", keep_default_na=False)
    assert events.loc[events.trial_id == "test_trial", "trial_type"].tolist() == ["unknown"] * 5
    assert events.loc[events.trial_id != "test_trial", "trial_type"].tolist() == ["n/a"] * 5
    assert json.loads(qc.read_text())["NTestTrialsRetained"] == 5


def _write_stop_dual_csv(path, exp_id, rows, shared):
    """Raw dual stop export: a trigger, a dropped lead-in, then ``rows``.

    ``rows`` are ``(trial_id, duration_ms, fields)`` in presentation order and
    use the package's block-end clock, so each event's onset is the previous
    event's end. The lead-in absorbs the discarded-volume shift.
    """
    base = {"exp_id": exp_id, "stimulus": np.nan, **{k: np.nan for k in shared}}
    out = [{
        **base, "trial_id": "fmri_trigger_initial", "time_elapsed": 5000,
        "block_duration": 100, "stim_duration": 0, "rt": 0,
        "key_press": -1, "correct_response": -1,
    }]
    elapsed = 5000
    for trial_id, duration, fields in [(rows[0][0], 12000, {})] + list(rows):
        elapsed += duration
        out.append({
            **base, "trial_id": trial_id, "time_elapsed": elapsed,
            "block_duration": duration, "stim_duration": duration,
            "rt": -1, "key_press": -1, "correct_response": -1, **fields,
        })
    pd.DataFrame(out).to_csv(path, index=False)
    return path


def test_stop_flanker_raw_fixation_label_is_canonicalized_before_cleanup(tmp_path):
    raw, tsv, qc = _canonical_run(tmp_path, task="stopSignalWFlanker")
    go = {"stop_signal_condition": "go", "flanker_condition": "congruent", "stop_acc": 1}
    stop = {"stop_signal_condition": "stop", "flanker_condition": "incongruent", "stop_acc": 1}
    _write_stop_dual_csv(
        raw, "stop_signal_with_flanker__fmri",
        # The raw export names the inter-trial screen 'fixation'.
        [("fixation", 1000, go),
         ("test_trial", 1000, {**go, "key_press": 37, "correct_response": 37, "rt": 450}),
         ("fixation", 1000, stop),
         ("test_trial", 1000, stop),
         ("feedback_block", 6000, {**stop, "stimulus": "You completed a block."})],
        shared=["SS_delay", "SS_duration", "stop_signal_condition",
                "flanker_condition", "SSD_congruent", "SSD_incongruent", "stop_acc"],
    )
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t", keep_default_na=False)
    assert events.trial_id.tolist() == [
        "test_fixation", "test_trial", "test_fixation", "test_trial", "break",
    ]
    assert events.trial_type.tolist() == [
        "fixation", "go_congruent", "fixation", "stop_success_incongruent", "n/a",
    ]
    assert events.onset.tolist() == pytest.approx([1.57, 2.57, 3.57, 4.57, 5.57])
    assert events.duration.tolist() == [1.0, 1.0, 1.0, 1.0, 6.0]
    assert json.loads(qc.read_text())["NTestTrialsRetained"] == 2


def test_stop_directed_forgetting_keeps_named_memory_phases(tmp_path):
    raw, tsv, qc = _canonical_run(tmp_path, task="stopSignalWDirectedForgetting")
    go = {"stop_signal_condition": "go", "directed_forgetting_condition": "con", "stop_acc": 1}
    _write_stop_dual_csv(
        raw, "stop_signal_with_directed_forgetting__fmri",
        # This task uses two raw fixation spellings; both are canonical
        # test_fixation. The letter set and the forget cue are separate events.
        [("ITI_fixation", 1000, go),
         ("stim", 2000, go),
         ("cue", 1000, go),
         ("fixation", 1000, go),
         ("test_trial", 1000, {**go, "key_press": 37, "correct_response": 37, "rt": 450}),
         ("feedback_block", 6000, {**go, "stimulus": "You completed a block."})],
        shared=["SS_delay", "SS_duration", "stop_signal_condition",
                "directed_forgetting_condition", "stop_acc"],
    )
    _create(tmp_path)
    events = pd.read_csv(tsv, sep="\t", keep_default_na=False)
    assert events.trial_id.tolist() == [
        "test_fixation", "test_stim", "test_cue", "test_fixation", "test_trial", "break",
    ]
    # The memory phases keep the raw condition they inherited; outcome
    # classification is confined to test_trial and never labels a cue.
    assert events.trial_type.tolist() == [
        "fixation", "go_con", "go_con", "fixation", "go_con", "n/a",
    ]
    assert "memory_cue" not in set(events.trial_type)
    # The GLM's memory_and_cue regressor selects these two rows by trial_id and
    # uses their recorded durations, whatever trial_type they carry.
    memory = events[events.trial_id.isin(["test_stim", "test_cue"])]
    assert memory.duration.tolist() == [2.0, 1.0]
    assert memory.onset.tolist() == pytest.approx([2.57, 4.57])
    assert events.onset.tolist() == pytest.approx([1.57, 2.57, 4.57, 5.57, 6.57, 7.57])
    assert json.loads(qc.read_text())["NTestTrialsRetained"] == 1
