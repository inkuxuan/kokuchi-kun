import pytest
import os
import json
import shutil
from utils.persistence import Persistence

class TestPersistence:
    @pytest.fixture
    def persistence(self):
        """Create a Persistence instance with a test directory."""
        test_dir = 'test_data'
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

        p = Persistence(data_dir=test_dir)
        yield p

        # Cleanup
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

    def test_ensure_data_dir(self, persistence):
        """Test that the data directory is created."""
        assert os.path.exists(persistence.data_dir)

    def test_save_and_load_data(self, persistence):
        """Test saving and loading valid JSON data."""
        filename = 'test.json'
        data = {'key': 'value', 'list': [1, 2, 3]}

        # Save
        assert persistence.save_data(filename, data) is True
        assert os.path.exists(os.path.join(persistence.data_dir, filename))

        # Load
        loaded_data = persistence.load_data(filename)
        assert loaded_data == data

    def test_load_nonexistent_file(self, persistence):
        """Test loading a file that doesn't exist returns default."""
        filename = 'nonexistent.json'
        default = {'default': True}

        loaded_data = persistence.load_data(filename, default)
        assert loaded_data == default

    def test_load_corrupt_file(self, persistence):
        """Test loading a corrupt JSON file returns default."""
        filename = 'corrupt.json'
        filepath = os.path.join(persistence.data_dir, filename)

        # Write invalid JSON
        with open(filepath, 'w') as f:
            f.write('{invalid json')

        default = {'default': True}
        loaded_data = persistence.load_data(filename, default)
        assert loaded_data == default

    def test_save_unicode(self, persistence):
        """Test saving unicode characters."""
        filename = 'unicode.json'
        data = {'text': 'こんにちは'}

        persistence.save_data(filename, data)
        loaded_data = persistence.load_data(filename)
        assert loaded_data == data
