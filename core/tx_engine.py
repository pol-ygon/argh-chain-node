# core/tx_engine.py
ALLOWED_ASSETS = {"ARGH", "aUSD"}

from config.settings import (
    BRIDGE_ISSUER_ADDRESS,
    EXPECTED_CHAIN_ID, 
    TREASURY_ADDRESS,
    TRANSFER_FEE_PERCENT,
    FEE_TO_DEVS,
    FEE_TO_ORBITAL,
    FEE_TO_VALIDATOR,
    DEVS_ADDRESS,
    ORBITAL_ADDRESS
)
from core.storage import ChainStorage
from eth_account import Account
from eth_account.messages import encode_defunct
from core.utils import canonical_tx

from core.utils import q
from decimal import Decimal

def k(addr, asset):
    return f"{addr}:{asset}"

def is_canonical_amount(x) -> bool:
    return Decimal(str(x)).as_tuple().exponent >= -8

class TransactionEngine:
    def __init__(self):
        self.storage = ChainStorage()
    
    @staticmethod
    def calculate_fee(amount: float) -> dict:
        total_fee = q(amount * TRANSFER_FEE_PERCENT)

        fee_devs = q(total_fee * FEE_TO_DEVS)
        fee_orbital = q(total_fee * FEE_TO_ORBITAL)
        fee_validator = q(total_fee - fee_devs - fee_orbital)

        return {
            "total": total_fee,
            "devs": fee_devs,
            "orbital": fee_orbital,
            "validator": fee_validator
        }
    
    def validate(self, tx: dict, balances: dict, *, system=False):
        action = tx.get("action")
        amount = tx.get("amount", 0)
        sender = tx.get("sender")

        # 0. BASIC CHECK
        if not action:
            raise ValueError("Missing action")

        if not sender and not system:
            raise ValueError("Missing sender")

        if amount <= 0:
            raise ValueError("Invalid amount")

        if not is_canonical_amount(amount):
            raise ValueError("Amount not canonical (max 8 decimals)")

        if tx.get("chainId") != EXPECTED_CHAIN_ID:
            raise ValueError("Invalid chainId")
    
        asset = tx.get("asset")
        if not asset:
            raise ValueError("Missing asset")

        # 2. SIGN (only user tx)
        if not system:
            signature = tx["_meta"]["signature"]
            sender = tx["_meta"]["sender"]

            signed_payload = {
                key: tx[key]
                for key in ("txid", "action", "asset", "amount", "to", "nonce", "chainId")
                if key in tx
            }


            message = canonical_tx(signed_payload)

            recovered = Account.recover_message(
                encode_defunct(text=message),
                signature=signature
            )

            if recovered.lower() != sender.lower():
                raise ValueError("Invalid signature")


        # 3. NONCE
        if not system:
            nonce = tx.get("nonce")
            if nonce is None:
                raise ValueError("Missing nonce")

            expected_nonce = self._calculate_nonce(sender)
            
            if nonce != expected_nonce:
                raise ValueError(
                    f"Invalid nonce: expected {expected_nonce}, got {nonce}"
                )


        # 4. ACTION RULES
        if action == "transfer":
            to = tx.get("to")
            if not to:
                raise ValueError("Invalid transfer")

            asset = tx["asset"]

            if asset not in ALLOWED_ASSETS:
                raise ValueError("Unsupported asset")

            if not system:
                fee_breakdown = self.calculate_fee(amount)
                fee_total = fee_breakdown["total"]
            else:
                fee_total = 0

            if asset == "ARGH":
                required = amount + fee_total
                if balances.get(f"{sender}:ARGH", 0) < required:
                    raise ValueError("Insufficient ARGH balance including fee")
            else:
                if balances.get(f"{sender}:{asset}", 0) < amount:
                    raise ValueError("Insufficient asset balance")

                if fee_total > 0:
                    if balances.get(f"{sender}:ARGH", 0) < fee_total:
                        raise ValueError("Insufficient ARGH balance for fee")

        elif action == "mint_bridge":
            if sender.lower() != BRIDGE_ISSUER_ADDRESS.lower():
                raise ValueError("Unauthorized bridge mint issuer")
            if not tx.get("to"):
                raise ValueError("mint_bridge missing recipient")
            if tx["asset"] not in ALLOWED_ASSETS:
                raise ValueError("Unsupported asset for bridge mint")

        elif action == "mint":

            if system:
                # ONLY allowed for ARGH protocol mint
                if tx["asset"] != "ARGH":
                    raise ValueError("Only ARGH can be system mint")
                return

            # bridge mint
            if sender.lower() != BRIDGE_ISSUER_ADDRESS.lower():
                raise ValueError("Unauthorized mint issuer")

            if not tx.get("to"):
                raise ValueError("Mint missing recipient")


        elif action == "burn":
            if not system and sender != TREASURY_ADDRESS:
                raise ValueError("Unauthorized burn")

        elif action == "add_liquidity":
            asset = tx.get("asset")
            asset_paired = tx.get("asset_paired")

            if not asset or not asset_paired:
                raise ValueError("Missing liquidity assets")

            if balances.get(k(sender, asset), 0) < tx["amount"]:
                raise ValueError("Insufficient balance for asset")

            if balances.get(k(sender, asset_paired), 0) < tx["amount_paired"]:
                raise ValueError("Insufficient balance for paired asset")
        
        elif action == "reward":
            if not system:
                raise ValueError("reward must be system tx")
            if not tx.get("to"):
                raise ValueError("reward missing recipient")

        else:
            raise ValueError("Unknown action")

    def _calculate_nonce(self, address: str) -> int:
        address = address.lower()
        chain = self.storage.load()
        
        nonce = 0
        for block in chain:
            for tx in block.get("transactions", []):
                if tx.get("sender", "").lower() == address:
                    nonce += 1
        
        return nonce

    def apply_tx(self, balances: dict, tx: dict, *, system=False, validator_address=None):
        action = tx["action"]
        amount = tx["amount"]
        sender = tx.get("sender")
        to = tx.get("to")
        fee = tx.get("_fee", {})

        if action == "transfer":
            asset = tx["asset"]
            fee_asset = "ARGH"

            # amount
            balances[k(sender, asset)] = balances.get(k(sender, asset), 0) - amount
            balances[k(to, asset)] = balances.get(k(to, asset), 0) + amount

            # fee: ONLY subtraction from the sender
            if fee and not system:
                balances[k(sender, fee_asset)] = balances.get(
                    k(sender, fee_asset), 0
                ) - fee["total"]


        elif action == "mint_bridge":
            asset = tx["asset"]
            balances[k(tx["to"], asset)] = balances.get(k(tx["to"], asset), 0) + amount

        elif action == "mint":
            asset = tx["asset"]
            balances[k(to, asset)] = balances.get(k(to, asset), 0) + amount

        elif action == "burn":
            asset = tx["asset"]
            balances[k(sender, asset)] = balances.get(k(sender, asset), 0) - amount

        elif action == "add_liquidity":
            asset = tx["asset"]
            asset_paired = tx["asset_paired"]

            balances[k(sender, asset)] = balances.get(k(sender, asset), 0) - tx["amount"]
            balances[k(sender, asset_paired)] = balances.get(k(sender, asset_paired), 0) - tx["amount_paired"]

            pool = f"POOL:{tx['pool_id']}"
            balances[k(pool, asset)] = balances.get(k(pool, asset), 0) + tx["amount"]
            balances[k(pool, asset_paired)] = balances.get(k(pool, asset_paired), 0) + tx["amount_paired"]

        elif action == "reward":
            asset = tx["asset"]
            balances[k(tx["to"], asset)] = balances.get(k(tx["to"], asset), 0) + tx["amount"]

        # nonce ONLY user tx
        if not system and sender:
            balances[f"_nonce_{sender}"] = balances.get(f"_nonce_{sender}", 0) + 1
