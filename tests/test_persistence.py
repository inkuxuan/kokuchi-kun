import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from utils.persistence import Persistence


class TestPersistence:
    @pytest.fixture
    def mock_db(self):
        """Create a mock Firestore AsyncClient."""
        db = MagicMock()
        return db

    @pytest.fixture
    def persistence(self, mock_db):
        """Create a Persistence instance with a mocked Firestore client."""
        with patch('utils.persistence.AsyncClient', return_value=mock_db):
            p = Persistence(server_id='test-server')
        return p

    @pytest.mark.asyncio
    async def test_save_data(self, persistence):
        """Test saving per-server data to Firestore."""
        doc_ref = MagicMock()
        doc_ref.set = AsyncMock()
        persistence.db.collection.return_value.document.return_value.collection.return_value.document.return_value = doc_ref

        result = await persistence.save_data('pending', {'key': 'value'})

        assert result is True
        doc_ref.set.assert_called_once_with({'data': {'key': 'value'}})

    @pytest.mark.asyncio
    async def test_load_data_exists(self, persistence):
        """Test loading existing per-server data from Firestore."""
        doc_snapshot = MagicMock()
        doc_snapshot.exists = True
        doc_snapshot.to_dict.return_value = {'data': {'key': 'value'}}

        doc_ref = MagicMock()
        doc_ref.get = AsyncMock(return_value=doc_snapshot)
        persistence.db.collection.return_value.document.return_value.collection.return_value.document.return_value = doc_ref

        result = await persistence.load_data('pending')

        assert result == {'key': 'value'}

    @pytest.mark.asyncio
    async def test_load_data_not_exists(self, persistence):
        """Test loading non-existent data returns default."""
        doc_snapshot = MagicMock()
        doc_snapshot.exists = False

        doc_ref = MagicMock()
        doc_ref.get = AsyncMock(return_value=doc_snapshot)
        persistence.db.collection.return_value.document.return_value.collection.return_value.document.return_value = doc_ref

        result = await persistence.load_data('pending', {'default': True})

        assert result == {'default': True}

    @pytest.mark.asyncio
    async def test_load_data_error_returns_default(self, persistence):
        """Test loading data with an error returns default."""
        doc_ref = MagicMock()
        doc_ref.get = AsyncMock(side_effect=Exception("Firestore error"))
        persistence.db.collection.return_value.document.return_value.collection.return_value.document.return_value = doc_ref

        result = await persistence.load_data('pending', {'default': True})

        assert result == {'default': True}

    @pytest.mark.asyncio
    async def test_save_shared(self, persistence):
        """Test saving shared data to Firestore."""
        doc_ref = MagicMock()
        doc_ref.set = AsyncMock()
        persistence.db.collection.return_value.document.return_value = doc_ref

        result = await persistence.save_shared('vrchat_session', {'authCookie': 'abc'})

        assert result is True
        doc_ref.set.assert_called_once_with({'authCookie': 'abc'})

    @pytest.mark.asyncio
    async def test_load_shared_exists(self, persistence):
        """Test loading existing shared data from Firestore."""
        doc_snapshot = MagicMock()
        doc_snapshot.exists = True
        doc_snapshot.to_dict.return_value = {'authCookie': 'abc'}

        doc_ref = MagicMock()
        doc_ref.get = AsyncMock(return_value=doc_snapshot)
        persistence.db.collection.return_value.document.return_value = doc_ref

        result = await persistence.load_shared('vrchat_session')

        assert result == {'authCookie': 'abc'}
