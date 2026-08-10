"""Static file serving: extension whitelist + mtime-based cachebusting.

`StaticFileWatcher` is lazy: constructing it does no filesystem work at all.
The first `version()` lookup overall starts the inotify watch (via watchfiles),
and the first lookup for each path stats that one file — the only stat it ever
gets, since later updates come from inotify events. A version is the file's
real mtime as an ISO-8601 UTC timestamp, so `?v=` tokens are readable, stable
across server restarts, and browser caches stay warm.

`CacheBustedMount` swaps in for the plain static `Mount`:
- `request.url_for('static', path=...)` transparently gains a `?v=<mtime>` query param
- requests for a watched file are refused (404) unless they carry the current `?v=`
- correct-version responses get an immutable Cache-Control header

Known (accepted) race: a file modified in the few ms between the first-ever
`version()` call and inotify registration completing keeps its stale version
until its next modification.
"""

import os
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders, URLPath
from starlette.responses import PlainTextResponse
from starlette.routing import Mount
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from watchfiles import watch


class StaticFilesWithWhitelist(StaticFiles):
    def __init__(self, directory: str, included_extensions: Sequence[str]):
        self.included_extensions = included_extensions
        super().__init__(directory=directory)

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        if not any(path.endswith(ext) for ext in self.included_extensions):
            # A null stat is how StaticFiles spells "not found", and it turns
            # into a plain 404 instead of a 500 from a raised OSError.
            return path, None
        return super().lookup_path(path)


class StaticFileWatcher:
    def __init__(self, directory: Path, included_extensions: Sequence[str], debounce: int = 1600, step: int = 25):
        self.root = directory.resolve()
        self._included_extensions = tuple(included_extensions)
        self._debounce = debounce
        self._step = step
        self.versions: dict[str, str] = {}
        self._stop_event = threading.Event()
        self._start_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def _is_watched(self, path: str) -> bool:
        return any(path.endswith(ext) for ext in self._included_extensions)

    def _ensure_watching(self):
        if self._thread is not None:
            return
        with self._start_lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._watch, name=f"StaticFileWatcher({self.root})", daemon=True)
            self._thread.start()

    def _stat_version(self, path: Path) -> str:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        # 'Z' rather than '+00:00': a literal '+' in a query string decodes as a space.
        return mtime.isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _watch(self):
        for changes in watch(self.root, debounce=self._debounce, step=self._step, stop_event=self._stop_event):
            for _change, changed_path in changes:
                rel = Path(changed_path).relative_to(self.root).as_posix()
                if rel not in self.versions:
                    continue  # never requested; the first request stats it fresh anyway
                try:
                    self.versions[rel] = self._stat_version(Path(changed_path))
                except OSError:  # deleted (or otherwise gone): untrack, so the next request stats fresh
                    self.versions.pop(rel, None)

    def version(self, path: str) -> str | None:
        """Cachebust token for a static-mount path (leading slash optional), or None if unwatched/missing."""
        key = path.lstrip('/')
        if key not in self.versions:
            if not self._is_watched(key):
                return None
            self._ensure_watching()
            try:
                self.versions[key] = self._stat_version(self.root / key)
            except OSError:
                return None
        return self.versions[key]

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()


class CacheBustedMount(Mount):
    def __init__(self, path: str, app: ASGIApp, name: str, watcher: StaticFileWatcher):
        super().__init__(path, app=app, name=name)
        self.watcher = watcher

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        url_path = super().url_path_for(name, **path_params)
        version = self.watcher.version(path_params['path']) if 'path' in path_params else None
        if version is None:
            return url_path
        return URLPath(f"{url_path}?v={version}", url_path.protocol, url_path.host)

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await super().handle(scope, receive, send)
            return

        route_path = scope["path"].removeprefix(scope.get("root_path", ""))
        version = self.watcher.version(route_path)
        if version is None:  # unwatched extension or missing file: the inner app 404s on its own
            await super().handle(scope, receive, send)
            return

        requested_version = parse_qs(scope["query_string"].decode()).get("v", [None])[-1]
        if requested_version != version:
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            return

        # A versioned URL changes whenever the file does, so the response is immutable.
        async def send_with_cache_header(message: Message):
            if message["type"] == "http.response.start" and message["status"] == 200:
                MutableHeaders(scope=message)["Cache-Control"] = "public, max-age=31536000, immutable"
            await send(message)

        await super().handle(scope, receive, send_with_cache_header)
