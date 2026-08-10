from pathlib import Path

import pytest

from y2k_fastapi_helpers.githash import githash

HASH = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    return tmp_path


def test_reads_hash_through_a_symbolic_head(repo: Path):
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/master\n")
    (repo / ".git" / "refs" / "heads" / "master").write_text(f"{HASH}\n")

    assert githash(repo) == HASH


def test_reads_hash_from_a_detached_head(repo: Path):
    (repo / ".git" / "HEAD").write_text(f"{HASH}\n")

    assert githash(repo) == HASH


def test_unreadable_repo_is_not_an_error(tmp_path: Path):
    assert githash(tmp_path) == 'githash_unknown'
