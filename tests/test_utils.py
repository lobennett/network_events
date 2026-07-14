import pandas as pd
import numpy as np
import pytest


def _make_basic_df():
    """Minimal behavioral CSV dataframe with timing columns."""
    return pd.DataFrame({
        "trial_id": ["fmri_trigger_initial", "test_trial", "test_trial", "test_trial"],
        "time_elapsed": [5000.0, 7000.0, 9000.0, 11000.0],
        "block_duration": [100.0, 2000.0, 2000.0, 2000.0],
        "rt": [0.0, 450.0, 520.0, -1.0],
        "key_press": [-1, 37, 39, -1],
        "correct_response": [-1, 37, 39, 37],
        "stim_duration": [0, 1500, 1500, 1500],
        "exp_id": ["stop_signal_single_task_network__fmri"] * 4,
        "stop_signal_condition": ["", "go", "go", "stop"],
    })


class TestCalTimeElapsed:
    def test_subtracts_trigger_time(self):
        from network_events.utils import cal_time_elapsed
        df = _make_basic_df()
        result = cal_time_elapsed(df)
        # trigger row: time_elapsed=5000, so subtract 5000, then subtract block_duration
        # row 0: 5000 - 5000 - 100 = -100
        # row 1: 7000 - 5000 - 2000 = 0
        # row 2: 9000 - 5000 - 2000 = 2000
        # row 3: 11000 - 5000 - 2000 = 4000
        assert result["time_elapsed"].iloc[1] == 0.0
        assert result["time_elapsed"].iloc[2] == 2000.0

    def test_no_trigger_raises(self):
        from network_events.utils import cal_time_elapsed
        df = _make_basic_df()
        df["trial_id"] = ["test_trial"] * 4
        with pytest.raises(IndexError):
            cal_time_elapsed(df)


class TestGetNegRtCorrection:
    def test_no_negative_rt_passthrough(self):
        from network_events.utils import get_neg_rt_correction
        df = _make_basic_df()
        result = get_neg_rt_correction(df)
        assert list(result["time_elapsed"]) == list(df["time_elapsed"])

    def test_negative_rt_corrected(self):
        from network_events.utils import get_neg_rt_correction
        df = _make_basic_df()
        # Introduce a negative RT to trigger correction
        df.loc[2, "rt"] = -500.0
        result = get_neg_rt_correction(df)
        # After correction, time_elapsed for rows 2+ should be recalculated
        assert result["time_elapsed"].iloc[2] == result["time_elapsed"].iloc[1] + df["block_duration"].iloc[2]


class TestAddChoiceAcc:
    def test_correct_responses(self):
        from network_events.utils import add_choice_acc
        df = _make_basic_df()
        result = add_choice_acc(df)
        assert result["choice_acc"].iloc[1] == 1  # 37 == 37
        assert result["choice_acc"].iloc[2] == 1  # 39 == 39
        assert result["choice_acc"].iloc[3] == 0  # -1 != 37


class TestAddCols:
    def test_stop_signal_columns(self):
        from network_events.utils import add_cols
        df = _make_basic_df()
        df["choice_acc"] = [0, 1, 1, 0]
        df["SS_delay"] = [0, 0, 0, 250]
        df["SS_duration"] = [0, 0, 0, 500]
        df["stop_acc"] = [0, 0, 0, 1]
        df["go_acc"] = [0, 1, 1, 0]
        df["stim"] = ["", "arrow_left", "arrow_right", "arrow_left"]
        result = add_cols(df, "stop_signal_single_task_network__fmri")
        assert "trial_type" in result.columns
        assert "SS_delay" in result.columns


class TestResponseTimeAndJunk:
    def test_stop_signal_trial_types(self):
        from network_events.utils import response_time_and_junk
        df = pd.DataFrame({
            "trial_id": ["test_trial", "test_trial", "test_trial"],
            "trial_type": ["go", "stop", "stop"],
            "choice_acc": [1, 1, 0],
            "stop_acc": [0, 1, 0],
        })
        result = response_time_and_junk(df, "stopSignal")
        assert result["trial_type"].iloc[0] == "go"
        assert result["trial_type"].iloc[1] == "stop_success"
        assert result["trial_type"].iloc[2] == "stop_failure"
