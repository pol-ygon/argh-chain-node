# core/utils.py
import json

def canonical_tx(tx: dict) -> str:
    """
    Returns the canonical representation of the tx
    with keys in a specific order (MUST match the frontend)
    """
    ordered = {
        "txid": tx.get("txid"),
        "action": tx.get("action"),
        "asset": tx.get("asset"),
        "amount": tx.get("amount"),
        "to": tx.get("to"),
        "nonce": tx.get("nonce"),
        "chainId": tx.get("chainId"),
    }

    return json.dumps(ordered, separators=(",", ":"))

def canonical_tx_consensus(tx: dict) -> str:
    ordered = {
        "txid": tx.get("txid"),
        "action": tx.get("action"),
        "asset": tx.get("asset"),
        "amount": tx.get("amount"),
        "to": tx.get("to"),
        "nonce": tx.get("nonce"),
        "chainId": tx.get("chainId"),
    }

    if tx["action"] == "add_liquidity":
        ordered.update({
            "pool_id": tx.get("pool_id"),
            "asset_paired": tx.get("asset_paired"),
            "amount_paired": tx.get("amount_paired"),
        })

    return json.dumps(ordered, separators=(",", ":"), sort_keys=True)


def norm(addr: str) -> str:
    return addr.lower()

def is_system_tx(tx: dict, protocol) -> bool:
    return (
        tx.get("sender") == protocol["treasury"]
        and tx.get("action") in ("mint", "burn", "add_liquidity")
    )

from decimal import Decimal, ROUND_DOWN

DECIMALS = Decimal("0.00000001")

def q(amount) -> float:
    return float(Decimal(str(amount)).quantize(DECIMALS, rounding=ROUND_DOWN))

def loading(NODE_ADDRESS):
    print(r'  /$$$$$$                      /$$              /$$$$$$  /$$                 /$$          ')
    print(r' /$$__  $$                    | $$             /$$__  $$| $$                |__/          ')
    print(r'| $$  \ $$  /$$$$$$   /$$$$$$ | $$$$$$$       | $$  \__/| $$$$$$$   /$$$$$$  /$$ /$$$$$$$ ')
    print(r'| $$$$$$$$ /$$__  $$ /$$__  $$| $$__  $$      | $$      | $$__  $$ |____  $$| $$| $$__  $$')
    print(r'| $$__  $$| $$  \__/| $$  \ $$| $$  \ $$      | $$      | $$  \ $$  /$$$$$$$| $$| $$  \ $$')
    print(r'| $$  | $$| $$      | $$  | $$| $$  | $$      | $$    $$| $$  | $$ /$$__  $$| $$| $$  | $$')
    print(r'| $$  | $$| $$      |  $$$$$$$| $$  | $$      |  $$$$$$/| $$  | $$|  $$$$$$$| $$| $$  | $$')
    print(r'|__/  |__/|__/       \____  $$|__/  |__/       \______/ |__/  |__/ \_______/|__/|__/  |__/')
    print(r'                     /$$  \ $$                                                            ')
    print(r'                    |  $$$$$$/                                                            ')
    print(r'                     \______/                                                             ')

    print("🚀 Node Starting... ")
    print(f"🆔 Node Wallet: {NODE_ADDRESS}")

def load_validators():
    with open("nodes.json") as f:
        nodes = json.load(f)

    VALIDATORS = sorted(node["id"].lower() for node in nodes)
    VALIDATOR_PUBKEYS = {
        node["id"].lower(): bytes.fromhex(node["pubkey"])
        for node in nodes
    }

    return VALIDATORS, VALIDATOR_PUBKEYS, nodes

def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

def get_protocol(chain):
    if not chain:
        return None

    first = chain[0]

    # Block object
    if hasattr(first, "protocol"):
        return first.protocol

    # Dict (API)
    if isinstance(first, dict):
        return first.get("protocol")

    return None