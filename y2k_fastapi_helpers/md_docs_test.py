from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from jinja2 import DictLoader, Environment, StrictUndefined

from y2k_fastapi_helpers.md_docs import create_md_docs_router

# A minimal stand-in for an app-owned page template exercising the whole contract.
PAGE = '<!doctype html><title>{{ path or "Docs" }}</title><style>{{ css }}</style><div class="md-docs">{{ menu }}{{ article }}</div>'


def make_client(md_root: Path) -> TestClient:
    env = Environment(loader=DictLoader({'md_docs.html': PAGE}), autoescape=True, undefined=StrictUndefined)
    app = FastAPI(default_response_class=HTMLResponse)
    app.include_router(create_md_docs_router(md_root, Jinja2Templates(env=env), 'md_docs.html'))
    return TestClient(app)


@pytest.fixture
def docs_root(tmp_path: Path) -> Path:
    (tmp_path / 'README.md').write_text('# Hello\n\nSee https://example.com and [todo](docs/TODO.md)')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs' / 'TODO.md').write_text('# Todo')
    (tmp_path / 'pyproject.toml').write_text('[project]')
    (tmp_path / '.secret').mkdir()
    (tmp_path / '.secret' / 'hidden.md').write_text('# hidden')
    return tmp_path


@pytest.fixture
def client(docs_root: Path) -> TestClient:
    return make_client(docs_root)


def test_browser_lists_markdown_files_recursively(client: TestClient):
    response = client.get("/md")
    assert response.status_code == 200
    assert "README.md" in response.text
    assert "docs/TODO.md" in response.text


def test_browser_prompts_for_a_selection(client: TestClient):
    assert "Select a document." in client.get("/md").text


def test_directory_paths_show_the_browser(client: TestClient):
    response = client.get("/md/docs")
    assert response.status_code == 200
    assert "docs/TODO.md" in response.text
    assert "Select a document." in response.text


def test_menu_persists_when_viewing_a_doc(client: TestClient):
    response = client.get("/md/README.md")
    # The menu still lists every doc, with the open one marked current.
    assert "docs/TODO.md" in response.text
    assert 'aria-current="page"' in response.text


def test_page_renders_markdown_in_the_article(client: TestClient):
    response = client.get("/md/README.md")
    assert response.status_code == 200
    assert "<article><h1>Hello</h1>" in response.text


def test_page_linkifies_bare_urls(client: TestClient):
    assert '<a href="https://example.com">' in client.get("/md/README.md").text


def test_relative_links_between_docs_resolve(client: TestClient):
    # README links to docs/TODO.md; from /md/README.md that resolves to /md/docs/TODO.md.
    response = client.get("/md/README.md")
    assert 'href="docs/TODO.md"' in response.text
    assert client.get("/md/docs/TODO.md").status_code == 200


def test_css_fragment_is_not_html_escaped(client: TestClient):
    # The selector's quotes must survive into the inline <style> tag.
    assert 'a[aria-current="page"]' in client.get("/md").text


def test_filenames_are_escaped_in_the_menu(tmp_path: Path):
    (tmp_path / 'a&b.md').write_text('# ampersand')
    response = make_client(tmp_path).get("/md")
    assert 'a&amp;b.md' in response.text


def test_non_markdown_files_are_not_served(client: TestClient):
    assert client.get("/md/pyproject.toml").status_code == 404


def test_missing_file_is_404(client: TestClient):
    assert client.get("/md/nope.md").status_code == 404


def test_hidden_paths_are_not_listed_or_served(client: TestClient):
    assert "hidden.md" not in client.get("/md").text
    assert client.get("/md/.secret/hidden.md").status_code == 404


def test_path_traversal_is_blocked(tmp_path: Path):
    (tmp_path / "outside.md").write_text("# outside")
    root = tmp_path / "root"
    root.mkdir()
    client = make_client(root)
    # Encoded slash so the client doesn't normalize the dot segment away before sending.
    assert client.get("/md/..%2Foutside.md").status_code == 404


def test_prefix_is_configurable(docs_root: Path):
    env = Environment(loader=DictLoader({'md_docs.html': PAGE}), autoescape=True, undefined=StrictUndefined)
    app = FastAPI(default_response_class=HTMLResponse)
    app.include_router(create_md_docs_router(docs_root, Jinja2Templates(env=env), 'md_docs.html', prefix="/help"))
    client = TestClient(app)
    assert client.get("/help").status_code == 200
    # The menu links follow the prefix.
    assert 'href="http://testserver/help/README.md"' in client.get("/help").text
