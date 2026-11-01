"""What chapter 11's pytest examples share: two fixtures, and a runner that prints one stable line per test.

    import pytest
    from lib.testing import anyio_backend, shop_api_env, run    # importing a fixture makes pytest use it
    pytestmark = pytest.mark.anyio                               # every async test runs on anyio's pytest plugin

    async def test_something(shop_api_env): ...                  # the shop's API on loopback, its address in os.environ

    if __name__ == "__main__":
        run(__file__)          # "test_something: passed", ..., then "tests passed: 1 of 1"

- `anyio_backend` returns "asyncio", the one event loop the book's examples use. anyio's pytest plugin ships with
  anyio, so async tests need no other plugin (https://anyio.readthedocs.io/en/stable/testing.html).
- `shop_api_env` serves the shop's API (`lib.shop_api`) on loopback for one test, puts `SHOP_API_URL` and
  `SHOP_API_KEY` in this process's environment, so a server whose tools run in this process can reach it, and
  yields the API's base URL. Each test gets a fresh API, so refunds one test records don't leak into the next.
  `shop_api_here()` does the same as a context manager, for examples that aren't tests: the tools of a server
  connected in-process, or served over loopback from this process, run here and read the API's address from here.
- `run(path)` runs the tests in `path` with pytest and prints each test's name and outcome, then the count that
  passed. pytest's own report prints timings and paths, which change from run to run, so `run` turns it off, along
  with pytest's cache, which would write to the examples folder. It collects with `--import-mode=importlib`,
  because the book's example files have hyphens in their names, and turns warnings into errors, as the book's
  examples run. A failing test prints its last error line after its name, and `run` exits with pytest's own exit
  code, so a failing test fails the example. `python -m pytest {file}` runs the same tests with pytest's usual report.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from lib import loopback, shop_api


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@contextmanager
def shop_api_here() -> Iterator[str]:
    """Serve the shop's API on loopback with its address in this process's environment; yield its base URL."""
    with loopback.serve(shop_api.create_app()) as base_url:
        saved = {name: os.environ.get(name) for name in ("SHOP_API_URL", "SHOP_API_KEY")}
        os.environ.update(shop_api.server_env(base_url))
        try:
            yield base_url
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@pytest.fixture
def shop_api_env() -> Iterator[str]:
    with shop_api_here() as base_url:
        yield base_url


class _Outcomes:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.passed = self.total = 0

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call" or (report.when == "setup" and not report.passed):
            self.total += 1
            self.passed += report.passed
            line = f"{report.head_line}: {report.outcome}"
            if report.failed:
                line += f" ({str(report.longrepr).strip().splitlines()[-1]})"
            self.lines.append(line)


def run(path: str) -> None:
    """Run the tests in `path`, print each test's outcome and the count that passed, and exit with pytest's code."""
    outcomes = _Outcomes()
    code = pytest.main([path, "--import-mode=importlib", "-p", "no:cacheprovider", "-p", "no:terminal",
                        # anyio is imported before pytest starts, so pytest can't rewrite its asserts: harmless
                        "-W", "error", "-W", "ignore::pytest.PytestAssertRewriteWarning"], plugins=[outcomes])
    for line in outcomes.lines:
        print(line)
    print("tests passed:", f"{outcomes.passed} of {outcomes.total}")
    sys.exit(int(code))
