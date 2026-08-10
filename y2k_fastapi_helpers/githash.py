from logging import getLogger
from pathlib import Path

logger = getLogger(__name__)


def githash(repo_path: Path | None = None) -> str:
    """The commit hash HEAD points at, or 'githash_unknown' if it can't be read."""
    repo_path = Path() if repo_path is None else repo_path
    head_file = repo_path / '.git' / 'HEAD'

    try:
        with head_file.open('r') as f:
            ref = f.readline().strip()

        if ref.startswith('ref:'):
            ref_path = repo_path / '.git' / ref.split(' ')[1]
            with ref_path.open('r') as f:
                return f.readline().strip()
        else:
            return ref
    except Exception as e:
        logger.exception(f"Unable to get githash: {e}")
        return 'githash_unknown'
