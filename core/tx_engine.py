# core/tx_engine.py

from core.storage import ChainStorage
from eth_account import Account
from eth_account.messages import encode_defunct
from core.utils import canonical_tx

from core.utils import q
from decimal import Decimal

def k(addr, asset):
    if addr and addr.startswith("0x"):
        addr = addr.lower()
    return f"{addr}:{asset}"

def is_canonical_amount(x) -> bool:
    return Decimal(str(x)).as_tuple().exponent >= -8

class TransactionEngine:
    def __init__(self):
        self.storage = ChainStorage()
    
    @staticmethod
    def calculate_fee(amount, protocol) -> dict:
        amount = Decimal(str(amount))

        percent = Decimal(protocol["transfer_fee_percent"])
        total_fee = amount * percent

        dev_ratio = Decimal(protocol["fee_distribution"]["devs"])
        orbital_ratio = Decimal(protocol["fee_distribution"]["orbital"])
        validator_ratio = Decimal(protocol["fee_distribution"]["validator"])

        fee_devs = total_fee * dev_ratio
        fee_orbital = total_fee * orbital_ratio
        fee_validator = total_fee - fee_devs - fee_orbital

        return {
            "total": q(total_fee),
            "devs": q(fee_devs),
            "orbital": q(fee_orbital),
            "validator": q(fee_validator)
        }

    
    def validate(self, tx: dict, balances: dict, protocol, system=False):
        action = tx.get("action")
        amount = tx.get("amount", 0)
        sender = tx.get("sender")

        native = protocol["native_asset"]
        treasury = protocol["treasury"].lower()

        # 0. BASIC CHECK
        if not action:
            raise ValueError("Missing action")

        if not sender and not system:
            raise ValueError("Missing sender")

        if amount <= 0:
            raise ValueError("Invalid amount")

        if not is_canonical_amount(amount):
            raise ValueError("Amount not canonical (max 8 decimals)")

        if tx.get("chainId") != protocol["chain_id"]:
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

            if asset not in protocol["allowed_assets"]:
                raise ValueError("Unsupported asset")

            if not system:
                fee_breakdown = self.calculate_fee(amount, protocol)
                fee_total = fee_breakdown["total"]
            else:
                fee_total = 0

            if asset == native:
                required = amount + fee_total
                if balances.get(k(sender, native), 0) < required:
                    raise ValueError(f"Insufficient {native} balance including fee")
            else:
                if balances.get(k(sender, asset), 0) < amount:
                    raise ValueError("Insufficient asset balance")

                if fee_total > 0:
                    if balances.get(k(sender, native), 0) < fee_total:
                        raise ValueError(f"Insufficient {native} balance for fee")

        elif action == "mint_bridge":
            if sender.lower() != protocol["bridge_issuer"].lower():
                raise ValueError("Unauthorized bridge mint issuer")
            if not tx.get("to"):
                raise ValueError("mint_bridge missing recipient")
            if tx["asset"] not in  protocol["allowed_assets"]:
                raise ValueError("Unsupported asset for bridge mint")

        elif action == "mint":

            if not system:
                raise ValueError("mint is protocol-only")

            if tx["asset"] != native:
                raise ValueError(f"Only {native} can be system mint")

            if tx.get("sender", "").lower() != treasury:
                raise ValueError("Mint sender must be treasury")

            if tx.get("to", "").lower() != treasury:
                raise ValueError("Mint recipient must be treasury")


        elif action == "burn":
            if not system:
                raise ValueError("burn is protocol-only")

            if tx.get("sender", "").lower() != treasury:
                raise ValueError("Burn sender must be treasury")

            if tx["asset"] != native:
                raise ValueError(f"Only {native} can be burned")

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
            if tx.get("sender") != "_protocol":
                raise ValueError("Invalid reward sender")

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

    def apply_tx(self, balances: dict, tx: dict, *, system=False, validator_address=None, protocol):
        action = tx["action"]
        amount = tx["amount"]
        sender = tx.get("sender").lower()
        to = tx.get("to")
        fee = tx.get("_fee", {})

        if action == "transfer":
            asset = tx["asset"]
            fee_asset = protocol["native_asset"]

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
