# core/crypto.py

from cryptography.fernet import Fernet
from pathlib import Path
import json

DATA_DIR = Path("/data")
FERNET_KEY_FILE = DATA_DIR / "node.fernet.key"


def load_or_create_key():
    if FERNET_KEY_FILE.exists():
        return FERNET_KEY_FILE.read_bytes()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    FERNET_KEY_FILE.write_bytes(key)
    return key


class CryptoStore:
    def __init__(self):
        self.key = load_or_create_key()
        self.fernet = Fernet(self.key)

    def encrypt(self, obj) -> bytes:
        raw = json.dumps(obj, sort_keys=True).encode()
        return self.fernet.encrypt(raw)

    def decrypt(self, data: bytes):
        raw = self.fernet.decrypt(data)
        return json.loads(raw)
