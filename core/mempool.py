from pathlib import Path
from core.crypto import CryptoStore

MEMPOOL_FILE = Path("/data/mempool.enc")

class Mempool:
    def __init__(self):
        self.crypto = CryptoStore()

        if not MEMPOOL_FILE.exists():
            MEMPOOL_FILE.parent.mkdir(parents=True, exist_ok=True)
            encrypted = self.crypto.encrypt([])
            MEMPOOL_FILE.write_bytes(encrypted)

    def add(self, tx_dict: dict):
        txs = self.load()

        if any(tx["txid"] == tx_dict["txid"] for tx in txs):
            print("⚠️ TX già presente in mempool:", tx_dict["txid"])
            return False

        txs.append(tx_dict)
        encrypted = self.crypto.encrypt(txs)
        MEMPOOL_FILE.write_bytes(encrypted)

        return True

    def load(self):

        if not MEMPOOL_FILE.exists():
            print("❌ MEMPOOL FILE NOT FOUND:", MEMPOOL_FILE)
            return []

        raw = MEMPOOL_FILE.read_bytes()

        try:
            txs = self.crypto.decrypt(raw)
            return txs
        except Exception as e:
            print("❌ MEMPOOL DECRYPT FAILED:", e)
            return []

    def flush(self):
        txs = self.load()
        if MEMPOOL_FILE.exists():
            MEMPOOL_FILE.unlink()
        return txs

    def remove_many(self, txids: set[str]):
        txs = self.load()
        txs = [tx for tx in txs if tx["txid"] not in txids]
        encrypted = self.crypto.encrypt(txs)
        MEMPOOL_FILE.write_bytes(encrypted)