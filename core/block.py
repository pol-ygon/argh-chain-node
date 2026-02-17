# core/block

import hashlib
import json
from datetime import datetime, timezone

from core.utils import canonical_tx_consensus

GENESIS_PRODUCER_ID = "0x0000000000000000000000000000000000000000"

def normalize_transactions(txs):
    out = []
    for tx in txs:
        if hasattr(tx, "to_dict"):
            tx = tx.to_dict()
        # remove None and sort keys
        out.append({k: tx[k] for k in sorted(tx) if tx[k] is not None})
    return out

class Block:
    def __init__(
        self,
        index: int,
        prev_hash: str,
        flare,
        geomag_factor,
        transactions: list,
        slot: int,
        producer_id: str | None = None,
        signature: str | None = None
    ):
        self.index = index
        self.prev_hash = prev_hash
        self.producer_id = producer_id
        self.signature = signature

        # timestamp
        self.block_time = datetime.now(timezone.utc).isoformat()

        # flare metadata
        if flare:
            self.flare_time = flare.ts
            self.flare_id = flare.id
            self.flare_class = flare.cls
            self.flare_flux = flare.flux
        else:
            # genesis
            self.block_time = "2000-10-31T07:52:47.000000+00:00"
            self.flare_time = "2000-10-31T07:52:47.000000+00:00"
            self.flare_id = "GENESIS"
            self.flare_class = "X"
            self.flare_flux = 1
            self.producer_id = GENESIS_PRODUCER_ID

        # geomag factor
        self.geomag_factor = geomag_factor

        # state
        self.transactions = transactions
        self.consensus_txs = [canonical_tx_consensus(tx) for tx in transactions]
        self.slot = slot 

        # hash
        self.hash = self.compute_hash()

    # --------------------------------------------------

    def compute_hash(self) -> str:
        payload = {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "producer_id": self.producer_id,
            "flare_id": self.flare_id,
            "flare_class": self.flare_class,
            "flare_flux": self.flare_flux,
            "geomag_factor": self.geomag_factor,
            "transactions": self.consensus_txs,
            "slot": self.slot,
        }

        encoded = json.dumps(payload, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    # --------------------------------------------------

    def get_flare_seed(self) -> dict:
        """
        Returns the deterministic seed used for leader selection
        based ONLY on block data.
        """
        # GENESIS or block without flare
        if self.flare_id == "GENESIS" or self.flare_flux is None:
            return {
                "time_tag": "",
                "satellite": 18,
                "flux": 0.0,
                "observed_flux": 0.0,
                "electron_correction": 0.0,
                "energy": "0.05-0.4nm",
            }

        return {
            "time_tag": self.flare_time or "",
            "satellite": 18,
            "flux": float(self.flare_flux),
            "observed_flux": float(self.flare_flux),
            "electron_correction": 0.0,
            "energy": "0.05-0.4nm",
        }

    def to_dict(self):
        return {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "hash": self.hash,

            # identity
            "producer_id": self.producer_id,
            "signature": self.signature,

            # timestamp
            "flare_time": self.flare_time,
            "block_time": self.block_time,

            # flare
            "flare": {
                "id": self.flare_id,
                "class": self.flare_class,
                "flux": self.flare_flux,
            },

            # geomag
            "geomag_factor": self.geomag_factor,

            # state
            "transactions": self.transactions,
            "slot": self.slot,
        }

    # --------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict):
        obj = cls.__new__(cls)  # bypass __init__

        
        obj.index = data["index"]
        obj.prev_hash = data["prev_hash"]
        obj.producer_id = data.get("producer_id")
        obj.signature = data.get("signature")

        # timestamp
        obj.flare_time = data["flare_time"]
        obj.block_time = data["block_time"]

        # flare
        obj.flare_id = data["flare"]["id"]
        obj.flare_class = data["flare"]["class"]
        obj.flare_flux = data["flare"]["flux"]

        # geomag
        obj.geomag_factor = data.get("geomag_factor", 0)

        # state
        obj.transactions = data.get("transactions", [])
        obj.consensus_txs = [canonical_tx_consensus(tx) for tx in obj.transactions]

        obj.slot = data["slot"]

        if obj.index == 0 and obj.producer_id != GENESIS_PRODUCER_ID:
            raise ValueError("Genesis producer_id non-canonical")

        # 🔐 calculate hash
        computed = obj.compute_hash()
        if computed != data["hash"]:
            raise ValueError("Invalid block hash")
        
        obj.hash = computed

        return obj
