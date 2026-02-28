import importlib.metadata
import logging

logger = logging.getLogger(__name__)

def get_version() -> str:
    """
    Reads the version from installed package metadata.
    Falls back to 'unknown' if the package is not installed.
    """
    try:
        return importlib.metadata.version('kokuchi-kun')
    except importlib.metadata.PackageNotFoundError:
        logger.error("Failed to load version: package 'kokuchi-kun' not found in metadata")
        return "unknown"
