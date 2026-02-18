import logging
from google.cloud.firestore_v1 import AsyncClient

logger = logging.getLogger(__name__)


class Persistence:
    def __init__(self, server_id='default', servers_collection='servers',
                 shared_collection='shared', state_subcollection='state'):
        self.server_id = server_id
        self.servers_collection = servers_collection
        self.shared_collection = shared_collection
        self.state_subcollection = state_subcollection
        self.db = AsyncClient()

    async def save_data(self, key, data):
        """Save per-server state to Firestore.

        Data is stored at {servers_collection}/{server_id}/{state_subcollection}/{key}.
        """
        try:
            doc_ref = (
                self.db.collection(self.servers_collection)
                .document(self.server_id)
                .collection(self.state_subcollection)
                .document(key)
            )
            await doc_ref.set({'data': data})
            return True
        except Exception as e:
            logger.error(f"Failed to save {key}: {e}")
            return False

    async def load_data(self, key, default=None):
        """Load per-server state from Firestore."""
        if default is None:
            default = {}

        try:
            doc_ref = (
                self.db.collection(self.servers_collection)
                .document(self.server_id)
                .collection(self.state_subcollection)
                .document(key)
            )
            doc = await doc_ref.get()
            if doc.exists:
                return doc.to_dict().get('data', default)
            return default
        except Exception as e:
            logger.error(f"Failed to load {key}: {e}")
            return default

    async def save_shared(self, key, data):
        """Save shared state (not scoped to a server) to Firestore.

        Data is stored at {shared_collection}/{key}.
        """
        try:
            doc_ref = self.db.collection(self.shared_collection).document(key)
            await doc_ref.set(data)
            return True
        except Exception as e:
            logger.error(f"Failed to save shared {key}: {e}")
            return False

    async def load_shared(self, key, default=None):
        """Load shared state from Firestore."""
        if default is None:
            default = {}

        try:
            doc_ref = self.db.collection(self.shared_collection).document(key)
            doc = await doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            return default
        except Exception as e:
            logger.error(f"Failed to load shared {key}: {e}")
            return default
