"""Cache safety when threads and processes share one SQLite file."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime

import pandas as pd
import pytest

from nba_insights.store import Cache

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX record locks")


def test_cache_runs_in_wal_mode(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite3")
    assert cache.journal_mode == "wal"
    # persistent: a second process opening the file sees WAL too
    with sqlite3.connect(tmp_path / "cache.sqlite3") as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_concurrent_writers_on_separate_instances_never_see_locked(tmp_path):
    path = tmp_path / "cache.sqlite3"
    Cache(path)
    errors: list[Exception] = []

    def writer(worker: int) -> None:
        cache = Cache(path)  # each worker has its own instance, as processes would
        try:
            for i in range(25):
                cache.put(f"w{worker}/{i}", pd.DataFrame({"v": range(200)}))
                cache.get(f"w{(worker + 1) % 8}/{i}")
        except sqlite3.OperationalError as error:
            errors.append(error)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert Cache(path).get("w7/24") is not None


_CHILD = """
import os, sys, time
from pathlib import Path
import pandas as pd
from nba_insights.store import Cache

db, workdir, worker = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
cache = Cache(db)
(workdir / f"ready-{worker}").touch()
while not (workdir / "go").exists():
    time.sleep(0.01)

def fetcher():
    with open(workdir / "fetches.txt", "a") as counter:
        counter.write("x")
    time.sleep(0.3)  # long enough that every process misses at once
    return pd.DataFrame({"PTS": [1, 2, 3]})

assert len(cache.get_or_fetch("league/2025-26", fetcher)) == 3
# Skip interpreter teardown: pyarrow's C++ thread pool can abort at exit
# ("terminate called without an active exception"), unrelated to the cache.
sys.stdout.flush()
os._exit(0)
"""


@posix_only
def test_a_miss_is_fetched_once_across_processes(tmp_path):
    # independent interpreters, like separate uvicorn workers
    (tmp_path / "fetches.txt").write_text("")
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(tmp_path / "c.sqlite3"), str(tmp_path), str(n)]
        )
        for n in range(4)
    ]
    deadline = time.monotonic() + 60
    while len(list(tmp_path.glob("ready-*"))) < 4:
        assert time.monotonic() < deadline, "workers did not start"
        time.sleep(0.05)
    (tmp_path / "go").touch()
    assert [worker.wait(timeout=60) for worker in workers] == [0, 0, 0, 0]
    assert (tmp_path / "fetches.txt").read_text() == "x"


_OPEN_CHILD = """
import os, sys, time
from pathlib import Path
from nba_insights.store import Cache

workdir, worker = Path(sys.argv[1]), sys.argv[2]
(workdir / f"ready-{worker}").touch()
while not (workdir / "go").exists():
    time.sleep(0.001)
try:
    Cache(workdir / "fresh.sqlite3")
except Exception as error:
    print(type(error).__name__, error, flush=True)
    os._exit(3)
os._exit(0)
"""


@posix_only
def test_workers_opening_a_fresh_cache_together_do_not_see_locked(tmp_path):
    # Switching a new file to WAL is not always covered by SQLite's busy
    # handler; unserialized, about 1 in 40 such opens failed "database is locked".
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", _OPEN_CHILD, str(tmp_path), str(n)],
            stdout=subprocess.PIPE,
            text=True,
        )
        for n in range(12)
    ]
    deadline = time.monotonic() + 60
    while len(list(tmp_path.glob("ready-*"))) < len(workers):
        assert time.monotonic() < deadline, "workers did not start"
        time.sleep(0.01)
    (tmp_path / "go").touch()
    outcomes = []
    for worker in workers:
        output, _ = worker.communicate(timeout=60)  # also closes the pipe
        outcomes.append((worker.returncode, output.strip()))
    assert outcomes == [(0, "")] * len(workers)
    assert Cache(tmp_path / "fresh.sqlite3").journal_mode == "wal"


def test_nested_fetch_in_one_process_does_not_deadlock(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite3")

    def outer() -> pd.DataFrame:
        # e.g. a fetcher that consults another cached frame first
        inner = cache.get_or_fetch("inner", lambda: pd.DataFrame({"a": [1]}))
        return inner.assign(b=2)

    finished = threading.Event()
    result: list[pd.DataFrame] = []
    worker = threading.Thread(
        target=lambda: (result.append(cache.get_or_fetch("outer", outer)), finished.set())
    )
    worker.start()
    assert finished.wait(timeout=10), "nested get_or_fetch deadlocked"
    assert result[0]["b"].tolist() == [2]


def test_foreign_non_parquet_row_is_a_miss_not_a_legacy_migration(tmp_path):
    path = tmp_path / "cache.sqlite3"
    cache = Cache(path)
    legacy = pd.DataFrame({"PTS": [1]}).to_json(orient="table")
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
            [
                ("v3:k", datetime(2026, 1, 2, tzinfo=UTC).isoformat(), "written by other tooling"),
                ("v2:k", datetime(2025, 1, 1, tzinfo=UTC).isoformat(), legacy),
            ],
        )
    assert cache.get("k") is None
    fresh = cache.get_or_fetch("k", lambda: pd.DataFrame({"PTS": [9]}))
    assert fresh["PTS"].tolist() == [9]
    assert cache.get("k")["PTS"].tolist() == [9]
