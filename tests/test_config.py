from network_events.config import N_DUMMY, TR_SECONDS

def test_acquisition_constants():
    assert N_DUMMY == 7
    assert TR_SECONDS == 1.49
    # dummy offset used for onset adjustment in create.py
    assert abs(N_DUMMY * TR_SECONDS - 10.43) < 1e-9
