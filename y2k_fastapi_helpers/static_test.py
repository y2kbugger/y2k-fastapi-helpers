import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from y2k_fastapi_helpers.static import CacheBustedMount, StaticFilesWithWhitelist, StaticFileWatcher


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def settle(watcher: StaticFileWatcher):
    """Give the lazily-started inotify registration a moment to complete before mutating files."""
    assert watcher._thread is not None, "settle() called before anything started the watch"
    time.sleep(0.3)


@pytest.fixture
def watcher(tmp_path: Path) -> Iterator[StaticFileWatcher]:
    (tmp_path / "a.css").write_text("body{}")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.js").write_text("let x = 1")
    (tmp_path / "notes.txt").write_text("not watched")
    w = StaticFileWatcher(tmp_path, ('css', 'js'), debounce=50, step=10)
    yield w
    w.stop()


def test_files_are_tracked_lazily_and_statted_once(watcher: StaticFileWatcher):
    assert watcher.versions == {}
    assert watcher._thread is None

    assert watcher.version("a.css") is not None
    assert watcher.version("/sub/b.js") is not None
    assert set(watcher.versions) == {"a.css", "sub/b.js"}
    assert watcher._thread is not None

    # unwatched extensions and missing files are not tracked
    assert watcher.version("notes.txt") is None
    assert watcher.version("missing.css") is None
    assert set(watcher.versions) == {"a.css", "sub/b.js"}


def test_version_is_the_iso_utc_mtime(watcher: StaticFileWatcher, tmp_path: Path):
    os.utime(tmp_path / "a.css", (1_000_000_000, 1_755_000_000.123))

    assert watcher.version("a.css") == "2025-08-12T12:00:00.123Z"


def test_modified_file_changes_version(watcher: StaticFileWatcher, tmp_path: Path):
    v1 = watcher.version("a.css")
    settle(watcher)

    os.utime(tmp_path / "a.css", ns=(0, (tmp_path / "a.css").stat().st_mtime_ns + 1_000_000_000))
    (tmp_path / "a.css").write_text("body{color:red}")
    assert wait_until(lambda: watcher.version("a.css") != v1)


def test_deleted_and_recreated_file_is_tracked(watcher: StaticFileWatcher, tmp_path: Path):
    assert watcher.version("a.css") is not None
    settle(watcher)

    (tmp_path / "a.css").unlink()
    assert wait_until(lambda: watcher.version("a.css") is None)

    (tmp_path / "a.css").write_text("back again")
    assert wait_until(lambda: watcher.version("a.css") is not None)


def test_file_created_after_failed_lookup_is_picked_up(watcher: StaticFileWatcher, tmp_path: Path):
    assert watcher.version("sub/c.css") is None

    (tmp_path / "sub" / "c.css").write_text("new")
    assert watcher.version("sub/c.css") is not None  # no event needed: an untracked path stats fresh


def test_version_survives_restart(tmp_path: Path):
    (tmp_path / "a.css").write_text("body{}")

    w1 = StaticFileWatcher(tmp_path, ('css',))
    v1 = w1.version("a.css")
    w1.stop()

    w2 = StaticFileWatcher(tmp_path, ('css',))
    assert w2.version("a.css") == v1
    w2.stop()


def test_cachebusted_mount_appends_version_via_url_for(watcher: StaticFileWatcher):
    async def dummy_app(scope, receive, send):  # noqa: ANN001
        raise NotImplementedError

    mount = CacheBustedMount("/static", app=dummy_app, name='static', watcher=watcher)

    assert str(mount.url_path_for('static', path='/a.css')) == f"/static/a.css?v={watcher.version('a.css')}"
    assert str(mount.url_path_for('static', path='/notes.txt')) == "/static/notes.txt"


@pytest.fixture
def client(tmp_path: Path, watcher: StaticFileWatcher) -> TestClient:
    app = FastAPI()
    app.router.routes.append(CacheBustedMount("/static", app=StaticFilesWithWhitelist(str(tmp_path), ('css', 'js')), name='static', watcher=watcher))
    return TestClient(app)


def test_serving_requires_the_correct_version(client: TestClient, watcher: StaticFileWatcher):
    v = watcher.version("a.css")

    ok = client.get(f"/static/a.css?v={v}")
    assert ok.status_code == 200
    assert ok.text == "body{}"
    assert ok.headers["Cache-Control"] == "public, max-age=31536000, immutable"

    assert client.get("/static/a.css").status_code == 404  # no version
    assert client.get("/static/a.css?v=deadbeef").status_code == 404  # wrong version

    assert client.get(f"/static/sub/b.js?v={watcher.version('sub/b.js')}").status_code == 200


def test_serving_stale_version_after_modification_is_refused(client: TestClient, watcher: StaticFileWatcher, tmp_path: Path):
    v1 = watcher.version("a.css")
    settle(watcher)

    os.utime(tmp_path / "a.css", ns=(0, (tmp_path / "a.css").stat().st_mtime_ns + 1_000_000_000))
    assert wait_until(lambda: watcher.version("a.css") != v1)

    assert client.get(f"/static/a.css?v={v1}").status_code == 404
    assert client.get(f"/static/a.css?v={watcher.version('a.css')}").status_code == 200


def test_unversionable_paths_fall_through_to_plain_404s(client: TestClient):
    # whitelist rejects the extension, so no version exists and no version is demanded
    assert client.get("/static/notes.txt").status_code == 404
    assert client.get("/static/missing.css").status_code == 404
