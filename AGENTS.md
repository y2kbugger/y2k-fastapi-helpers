# AGENTS.md

## Layout

Each module under `y2k_fastapi_helpers/` is an independent helper with its own
dependencies. Modules never import each other, and **`__init__.py` stays empty** — no
re-exports. Importing the package must not drag in FastAPI, a watcher thread, or any
other import-time cost that a consumer of one helper didn't ask for; consumers import
the submodule they want (`from y2k_fastapi_helpers.static import CacheBustedMount`).

`py.typed` ships with the package, so consumers type-check against the real
annotations. Keep public functions and classes annotated.

## Tests

`python_files = "*_test.py"` — a file named `test_foo.py` will be silently ignored by
both pytest and the VS Code test runner. Name it `foo_test.py`, next to the module it
covers.

Tests that touch the filesystem watcher are timing-sensitive: use the `wait_until`
helper rather than a bare `sleep`, and call `settle()` before mutating a file so the
lazily-started inotify registration has completed.

## Checks

```sh
uv run ruff check .
uv run ty check
uv run pytest
```
