# core/storage.py
from pathlib import Path
from core.crypto import CryptoStore

CHAIN_FILE = Path("/data/chain.enc")

class ChainStorage:
    def __init__(self):
        self.crypto = CryptoStore()

    def save(self, chain):
        payload = [block.to_dict() for block in chain]
        encrypted = self.crypto.encrypt(payload)
        CHAIN_FILE.write_bytes(encrypted)

    def load(self):
        if not CHAIN_FILE.exists():
            return []
        encrypted = CHAIN_FILE.read_bytes()
        return self.crypto.decrypt(encrypted)
