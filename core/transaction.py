# core/transaction.py
import hashlib
import json

from core.utils import q


class Transaction:
    def __init__(
        self,
        sender,
        to,
        action,
        asset,
        amount,
        nonce,
        chainId=1,
        timestamp=None,
        asset_paired=None,
        amount_paired=None,
    ):
        self.sender = sender.lower() if sender else sender
        self.to = to.lower() if to else to
        self.action = action
        self.asset = asset
        self.amount = q(amount)
        self.nonce = nonce
        self.chainId = chainId

        # only for liquidity
        self.asset_paired = asset_paired
        self.amount_paired = amount_paired

        # assigned by the node
        self.timestamp = timestamp

        self.txid = self.hash()

    def hash(self):
        """
        Deterministic, asset-aware TXID
        """
        payload = {
            "sender": self.sender,
            "to": self.to,
            "action": self.action,
            "asset": self.asset,
            "amount": self.amount,
            "nonce": self.nonce,
            "chainId": self.chainId,
        }

        if self.action == "add_liquidity":
            payload["asset_paired"] = self.asset_paired
            payload["amount_paired"] = self.amount_paired

        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self):
        tx = {
            "txid": self.txid,
            "sender": self.sender,
            "to": self.to,
            "action": self.action,
            "asset": self.asset,
            "amount": self.amount,
            "nonce": self.nonce,
            "chainId": self.chainId,
            "timestamp": self.timestamp,
        }

        if self.action == "add_liquidity":
            tx["asset_paired"] = self.asset_paired
            tx["amount_paired"] = self.amount_paired

        return tx
