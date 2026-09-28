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

## `y2k_fastapi_helpers.md_docs`

A browsable rendering of a directory tree of markdown files — read your repo's own
docs inside the app. Needs the `md-docs` extra:

```toml
dependencies = ["y2k-fastapi-helpers[md-docs]"]
```

The library owns the routes (listing, rendering, traversal/hidden-file guards) but
**the app owns the page template**, so the docs pages inherit your layout, nav, and
styling with no coupling to the library:

```python
from y2k_fastapi_helpers.md_docs import create_md_docs_router

app.include_router(create_md_docs_router(REPO_ROOT, templates, 'md_docs.html'))
```

Every render passes the template pre-built fragments (as `Markup` — no `| safe`
needed), plus the raw data they were built from so you can take over any level of the
markup:

| name | contents |
|---|---|
| `menu` | `<aside>` nav of every doc, the open one marked `aria-current="page"` |
| `article` | `<article>` of rendered markdown, or a "select a document" prompt |
| `css` | the bundled stylesheet, for inlining in a `<style>` tag |
| `path` / `files` | current doc path and the full listing, for custom markup |

A complete template, assuming a pico-style layout:

```html
{% extends "common/layout.html" %}

{% block title %}{{ path or 'Docs' }}{% endblock %}

{% block style %}
<style>
  {{ css }}
</style>
{% endblock style %}

{% block content %}
<div class="md-docs">
  {{ menu }}
  {{ article }}
</div>
{% endblock content %}
```

The bundled CSS styles `aside` and `article` structurally inside a `.md-docs` grid
container, so wrap the two fragments exactly as above (or ignore `css` and write your
own).

- Markdown renders with markdown-it's `gfm-like` preset: tables, strikethrough, and
  linkified bare URLs.
- The URL space mirrors the file layout under `md_root` (`/md/docs/TODO.md` ⇢
  `docs/TODO.md`), so relative links between documents resolve on their own.
- Hidden files and directories (`.git`, `.venv`, ...) are never listed or served;
  non-markdown files and paths escaping the root are 404s.
- Routes are named `md_docs_browser` and `md_docs_page` for `url_for`; mount point is
  the `prefix` argument (default `/md`).

## Checks

```sh
uv run ruff check .
uv run ty check
uv run pytest
```
