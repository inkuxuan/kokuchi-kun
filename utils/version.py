import tomli
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def get_version() -> str:
    """
    Reads the version from pyproject.toml.
    This serves as the single source of truth for the application version.
    """
    try:
        # Find the root directory (assuming this file is in utils/)
        root_dir = Path(__file__).parent.parent
        pyproject_path = root_dir / 'pyproject.toml'

        with open(pyproject_path, 'rb') as f:
            pyproject = tomli.load(f)
            return pyproject['project']['version']
    except Exception as e:
        logger.error(f"Failed to load version from pyproject.toml: {e}")
        return "unknown"
