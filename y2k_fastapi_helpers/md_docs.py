"""Markdown docs browser: browse and read a directory tree of .md files inside the app's own page template.

The app owns the template; each route passes it pre-rendered fragments plus the
raw data they were built from, so an app can take over at any level:

- `menu` — `<aside>` nav listing every doc, the open one marked `aria-current="page"`
- `article` — `<article>` with the rendered markdown (or a "select a document" prompt)
- `css` — the bundled stylesheet, for inlining in a `<style>` tag
- `path`, `files` — the current doc and the full listing, for custom markup

All fragments are `Markup`, so templates need no `| safe`.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup

MD_DOCS_CSS = Markup((Path(__file__).parent / 'md_docs.css').read_text())

# "gfm-like" bundles tables, strikethrough, and linkify (bare URLs become links).
_md = MarkdownIt("gfm-like")


def render_markdown(text: str) -> Markup:
    return Markup(_md.render(text))


def _is_visible(relative: Path) -> bool:
    """Hidden files and directories (.venv, .git, ...) are never listed or served."""
    return not any(part.startswith('.') for part in relative.parts)


def create_md_docs_router(md_root: Path, templates: Jinja2Templates, template_name: str, prefix: str = "/md") -> APIRouter:
    """Routes named `md_docs_browser` (the listing) and `md_docs_page` (one doc).

    Relative links between documents resolve on their own because the URL space
    under `prefix` mirrors the file layout beneath `md_root`.
    """
    md_root = md_root.resolve()
    router = APIRouter(prefix=prefix)

    def md_files() -> list[str]:
        return sorted(str(p.relative_to(md_root)) for p in md_root.rglob('*.md') if _is_visible(p.relative_to(md_root)))

    def menu(request: Request, files: list[str], current: str | None) -> Markup:
        items = Markup('').join(
            Markup('<li><a href="{}"{}>{}</a></li>').format(
                request.url_for('md_docs_page', path=file),
                Markup(' aria-current="page"') if file == current else '',
                file,
            )
            for file in files
        )
        return Markup('<aside><ul>{}</ul></aside>').format(items)

    def page(request: Request, path: str | None, body: Markup | None) -> Response:
        files = md_files()
        article = Markup('<article>{}</article>').format(body if body is not None else Markup('<p>Select a document.</p>'))
        context = {"path": path, "files": files, "css": MD_DOCS_CSS, "menu": menu(request, files, path), "article": article}
        return templates.TemplateResponse(request, template_name, context)

    @router.get("", name="md_docs_browser")
    def md_docs_browser(request: Request) -> Response:
        return page(request, None, None)

    @router.get("/{path:path}", name="md_docs_page")
    def md_docs_page(request: Request, path: str) -> Response:
        target = (md_root / path).resolve()
        if not target.is_relative_to(md_root) or not target.exists():
            raise HTTPException(status_code=404)
        relative = target.relative_to(md_root)
        if not _is_visible(relative):
            raise HTTPException(status_code=404)
        if target.is_dir():
            return page(request, None, None)
        if target.suffix != '.md':
            raise HTTPException(status_code=404)
        return page(request, str(relative), render_markdown(target.read_text()))

    return router
