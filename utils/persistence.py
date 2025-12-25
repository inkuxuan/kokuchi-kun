import json
import os
import logging
from utils.messages import Messages

logger = logging.getLogger(__name__)

class Persistence:
    def __init__(self, data_dir='data'):
        self.data_dir = data_dir
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        """Ensure the data directory exists"""
        if not os.path.exists(self.data_dir):
            try:
                os.makedirs(self.data_dir)
                logger.info(f"Created data directory: {self.data_dir}")
            except Exception as e:
                logger.error(f"Failed to create data directory: {e}")

    def save_data(self, filename, data):
        """Save data to a JSON file"""
        try:
            filepath = os.path.join(self.data_dir, filename)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # logger.debug(f"Saved data to {filename}") # Reduce noise
            return True
        except Exception as e:
            logger.error(f"Failed to save {filename}: {e}")
            return False

    def load_data(self, filename, default=None):
        """Load data from a JSON file"""
        if default is None:
            default = {}

        try:
            filepath = os.path.join(self.data_dir, filename)
            if not os.path.exists(filepath):
                return default

            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {filename}: {e}")
            return default
