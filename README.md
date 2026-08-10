# y2k-fastapi-helpers

Small FastAPI helpers, extracted from `insync_datastar`.

## Install

```toml
# pyproject.toml
dependencies = ["y2k-fastapi-helpers"]

[tool.uv.sources]
y2k-fastapi-helpers = { git = "https://github.com/y2kbugger/y2k-fastapi-helpers.git" }
```

## `y2k_fastapi_helpers.static`

Static file serving with an extension whitelist and mtime-based cachebusting.

```python
from pathlib import Path

from y2k_fastapi_helpers.static import CacheBustedMount, StaticFilesWithWhitelist, StaticFileWatcher

STATIC_DIR = Path("myapp/")
STATIC_EXTENSIONS = ('css', 'js', 'svg', 'png', 'ico', 'webmanifest')

watcher = StaticFileWatcher(STATIC_DIR, STATIC_EXTENSIONS)
app.router.routes.append(
    CacheBustedMount(
        "/static",
        app=StaticFilesWithWhitelist(str(STATIC_DIR), STATIC_EXTENSIONS),
        name='static',
        watcher=watcher,
    )
)
```

`app.mount()` only ever builds a plain `Mount`, hence appending the route directly.

Templates need no changes — `request.url_for('static', path='/layout.css')` gains the
version automatically:

```
/static/layout.css?v=2026-08-10T16:56:29.610Z
```

- **A version is the file's real mtime** as an ISO-8601 UTC timestamp, so tokens are
  readable and survive server restarts — browser caches stay warm across a redeploy of
  unchanged assets.
- **A watched file is served only with its current `?v=`.** A missing or stale version
  is a 404, so a stale URL can never be answered with fresh bytes. Correct-version
  responses carry `Cache-Control: public, max-age=31536000, immutable`.
- **Tracking is lazy and never polls.** Constructing the watcher does no filesystem
  work; the first lookup of a path stats that one file and starts an inotify watch
  (via `watchfiles`), and every later update arrives as a kernel event. Linux only in
  practice — `watchfiles` falls back to polling where inotify is unavailable.

Call `watcher.stop()` to shut the watch thread down; it is a daemon thread, so this is
only needed in tests.

## `y2k_fastapi_helpers.githash`

Reads the commit hash `HEAD` points at, without shelling out to git or requiring a
`.git` directory to exist:

```python
from y2k_fastapi_helpers.githash import githash

__githash__ = githash()          # cwd
__githash__ = githash(repo_path) # elsewhere
```

Returns `'githash_unknown'` rather than raising when there's nothing to read.

## Checks

```sh
uv run ruff check .
uv run ty check
uv run pytest
```
