# core/block

import hashlib
import json
from datetime import datetime, timezone
from core.utils import canonical_tx_consensus

GENESIS_PRODUCER_ID = "0x0000000000000000000000000000000000000000"


class Block:
    def __init__(
        self,
        index: int,
        prev_hash: str,
        transactions: list,
        slot: int,
        producer_id: str,
        flare_commit: str | None = None,
        signature: str | None = None,
        protocol: dict | None = None
    ):
        self.index = index
        self.prev_hash = prev_hash
        self.producer_id = producer_id
        self.signature = signature

        self.slot = slot
        self.block_time = datetime.now(timezone.utc).isoformat()

        # Consensus-critical
        self.transactions = transactions
        self.consensus_txs = [canonical_tx_consensus(tx) for tx in transactions]

        self.flare_commit = flare_commit

        # Genesis override
        if self.index == 0:
            self.producer_id = GENESIS_PRODUCER_ID
            self.block_time = "2000-10-31T07:52:47.000000+00:00"

        self.protocol = protocol

        self.hash = self.compute_hash()

    # --------------------------------------------------

    def compute_hash(self) -> str:
        """
        SOLO dati consensus-critical.
        Nessun flare_flux diretto.
        """

        payload = {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "producer_id": self.producer_id,
            "slot": self.slot,
            "transactions": self.consensus_txs,
            "flare_commit": self.flare_commit
        }
            
        if self.protocol is not None:
            payload["protocol"] = self.protocol

        encoded = json.dumps(payload, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    # --------------------------------------------------

    def get_leader_seed(self) -> str:
        """
        Leader selection NON dipende dal flare.
        Usa solo hash del blocco.
        """
        return self.hash

    # --------------------------------------------------

    def to_dict(self):
        data = {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
            "producer_id": self.producer_id,
            "signature": self.signature,
            "slot": self.slot,
            "block_time": self.block_time,
            "flare_commit": self.flare_commit,
            "transactions": self.transactions,
        }

        if self.protocol is not None:
            data["protocol"] = self.protocol

        return data

    # --------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict):
        obj = cls.__new__(cls)

        obj.index = data["index"]
        obj.prev_hash = data["prev_hash"]
        obj.producer_id = data.get("producer_id")
        obj.signature = data.get("signature")
        obj.slot = data["slot"]
        obj.block_time = data["block_time"]

        obj.transactions = data.get("transactions", [])
        obj.consensus_txs = [
            canonical_tx_consensus(tx) for tx in obj.transactions
        ]

        obj.flare_commit = data.get("flare_commit")

        obj.protocol = data.get("protocol")

        # Genesis validation
        if obj.index == 0 and obj.producer_id != GENESIS_PRODUCER_ID:
            raise ValueError("Genesis producer_id non-canonical")

        # Recompute hash
        computed = obj.compute_hash()
        if computed != data["hash"]:
            raise ValueError("Invalid block hash")

        obj.hash = computed
        return obj
