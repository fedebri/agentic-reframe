"""Exercise the actual pytest gates in isolated subprocesses, without API calls."""

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("arguments", "has_key", "expected"),
    [
        ([], True, "skipped"),
        (["--run-live"], True, "positive finite --live-budget-usd"),
        (["--run-live", "--live-budget-usd", "NaN"], True, "positive finite"),
        (["--run-live", "--live-budget-usd", "invalid"], True, "positive decimal"),
        (["--run-live", "--live-budget-usd", "0.05"], False, "requires OPENAI_API_KEY"),
        (["--run-live", "--live-budget-usd", "0.05"], True, "passed"),
    ],
)
def test_live_consent_gate(pytester, monkeypatch, arguments, has_key, expected):
    root = Path(__file__).resolve().parents[2]
    pytester.makeconftest((root / "tests" / "conftest.py").read_text())
    pytester.makeini("[pytest]\nmarkers = live: real service test\n")
    live_directory = pytester.mkdir("live")
    (live_directory / "test_gate.py").write_text(
        "from decimal import Decimal\n"
        "def test_gate(live_budget):\n"
        "    assert live_budget == Decimal('0.05')\n"
    )
    if has_key:
        monkeypatch.setenv("OPENAI_API_KEY", "fictional-key-no-api-call")
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = pytester.runpytest_subprocess("-q", *arguments)
    if expected in {"passed", "skipped"}:
        assert result.ret == 0
        result.assert_outcomes(**{expected: 1})
    else:
        assert result.ret == pytest.ExitCode.USAGE_ERROR
        assert expected in result.stderr.str()


def test_local_network_is_blocked(pytester):
    root = Path(__file__).resolve().parents[2]
    pytester.makeconftest((root / "tests" / "conftest.py").read_text())
    pytester.makepyfile(
        "import socket\n"
        "import pytest\n"
        "def test_offline():\n"
        "    with pytest.raises(AssertionError, match='Network access is disabled'):\n"
        "        socket.getaddrinfo('example.invalid', 443)\n"
        "    with socket.socket() as connection:\n"
        "        with pytest.raises(AssertionError, match='Network access'):\n"
        "            connection.connect(('127.0.0.1', 443))\n"
    )
    pytester.runpytest_subprocess("-q").assert_outcomes(passed=1)
