"""Explicit live-test consent and an offline boundary for all other tests."""

import os
import socket
from decimal import Decimal, InvalidOperation

import pytest

pytest_plugins = ["pytester"]


def pytest_addoption(parser: pytest.Parser) -> None:
    """Expose deliberate consent and a budget for real service tests."""
    group = parser.getgroup("live API tests")
    group.addoption(
        "--run-live", action="store_true", help="Enable tests that call the real API"
    )
    group.addoption(
        "--live-budget-usd", help="Explicit estimated USD budget for the live smoke run"
    )


def pytest_configure(config: pytest.Config) -> None:
    """Reject incomplete live-test authorization before collection."""
    if not config.getoption("--run-live"):
        return
    value = config.getoption("--live-budget-usd")
    try:
        budget = Decimal(value) if value is not None else Decimal("NaN")
    except InvalidOperation as error:
        raise pytest.UsageError(
            "--live-budget-usd must be a positive decimal"
        ) from error
    if not budget.is_finite() or budget <= 0:
        raise pytest.UsageError(
            "--run-live requires a positive finite --live-budget-usd"
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise pytest.UsageError("--run-live requires OPENAI_API_KEY in the environment")
    config.option.live_budget_usd = budget


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Gate the live directory even when a test author forgets its marker."""
    for item in items:
        if "live" in item.path.relative_to(config.rootpath).parts:
            item.add_marker(pytest.mark.live)
        if item.get_closest_marker("live") and not config.getoption("--run-live"):
            item.add_marker(
                pytest.mark.skip(reason="Real API tests require --run-live")
            )


@pytest.fixture(autouse=True)
def offline_by_default(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An API key in the shell must not turn a local test into a paid call."""
    if request.node.get_closest_marker("live"):
        return

    def block_network(*_args, **_kwargs):
        raise AssertionError("Network access is disabled in local tests")

    monkeypatch.setattr(socket.socket, "connect", block_network)
    monkeypatch.setattr(socket, "getaddrinfo", block_network)


@pytest.fixture(scope="session")
def live_budget(pytestconfig: pytest.Config) -> Decimal:
    """Return the budget validated by the explicit live-test gate."""
    return pytestconfig.getoption("--live-budget-usd")
