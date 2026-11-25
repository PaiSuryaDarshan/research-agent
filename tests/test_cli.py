import pytest

from research_agent.cli import main


def test_run_exits_zero(capsys):
    assert main(["run", "Battery interfaces", "--setup", "local"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "pipeline not implemented yet",
        "Topic: Battery interfaces",
        "Setup: local",
    ]


def test_run_echoes_topic(capsys):
    topic = "Evidence for superconductivity at ambient pressure"
    main(["run", topic])
    assert f"Topic: {topic}" in capsys.readouterr().out.splitlines()


def test_run_defaults_to_local(capsys):
    main(["run", "Battery interfaces"])
    assert "Setup: local" in capsys.readouterr().out.splitlines()


def test_run_rejects_unknown_setup(capsys):
    with pytest.raises(SystemExit) as error:
        main(["run", "Battery interfaces", "--setup", "unknown"])

    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
