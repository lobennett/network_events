import pytest
from network_events import cli

def test_cli_routes_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "_run", lambda a: seen.update(cmd="run", bids=a.bids_dir))
    cli.main(["run", "--behavioral-dir", "/b", "--bids-dir", "/x"])
    assert seen["cmd"] == "run" and seen["bids"] == "/x"

def test_cli_requires_subcommand():
    with pytest.raises(SystemExit):
        cli.main([])
