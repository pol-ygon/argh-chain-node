from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.block import Block
from core.mempool import Mempool
from core.state import compute_balances, compute_nonces, compute_pools
from core.storage import ChainStorage
from core.tx_engine import TransactionEngine, is_canonical_amount
from core.utils import canonical_tx, get_protocol

import uuid
import time

from eth_account import Account
from eth_account.messages import encode_defunct

def norm(addr: str) -> str:
    return addr.lower() if addr else addr

def tx_involves_address(tx: dict, address: str) -> bool:
    sender = norm(tx.get("sender"))
    to = norm(tx.get("to"))
    return sender == address or to == address

from datetime import datetime

def iso_to_ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())

CHALLENGE_TTL = 300  # seconds

challenges = {}

app = FastAPI(
    title="Argh Blockchain API",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = ChainStorage()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/chain")
def get_chain():
    return storage.load()

@app.get("/chain/latest")
def get_latest_block():
    chain = storage.load()
    if not chain:
        return None
    return chain[-1]

@app.get("/treasury")
def get_treasury():
    chain = storage.load()
    protocol = get_protocol(chain)
    
    balances = compute_balances(chain, protocol)
    treasury_key = f"{protocol['treasury'].lower()}:{protocol['native_asset']}"
    treasury_balance = balances.get(treasury_key, 0)
    
    return {
        "treasury": treasury_balance,
        "block": len(chain) - 1 if chain else 0
    }

@app.get("/nonce/{address}")
def get_nonce(address: str):
    address = norm(address)
    chain = storage.load()

    nonce = 0

    for block in chain:
        for tx in block.get("transactions", []):
            if tx.get("sender") == address:
                if "nonce" in tx:
                    nonce = max(nonce, tx["nonce"] + 1)

    return {
        "address": address,
        "nonce": nonce
    }

@app.post("/tx/send")
async def send_tx(payload: dict):
    mempool = Mempool()
    storage = ChainStorage()

    chain = storage.load()
    protocol = get_protocol(chain)

    tx = payload["tx"]
    signature = payload["signature"]

    signed_payload = {
        key: tx[key]
        for key in ("txid", "action", "asset", "amount", "to", "nonce", "chainId")
        if key in tx
    }

    message = canonical_tx(signed_payload)

    try:
        recovered = Account.recover_message(
            encode_defunct(text=message),
            signature=signature
        )
    except Exception:
        return {"ok": False, "error": "Invalid signature format"}

    sender = recovered.lower()

    # complete tx
    tx["sender"] = sender.lower()
    tx["timestamp"] = int(time.time())

    tx["_meta"] = {
        "sender": sender,
        "signature": signature,
        "received_at": int(time.time()),
    }

    if "to" in tx:
        tx["to"] = tx["to"].lower()

    # --- PROTOCOL CHECKS ---
    if tx.get("chainId") != protocol["chain_id"]:
        return {"ok": False, "error": "Invalid chainId"}

    if tx.get("asset") not in protocol["allowed_assets"]:
        return {"ok": False, "error": "Unsupported asset"}

    if tx.get("amount", 0) <= 0:
        return {"ok": False, "error": "Invalid amount"}

    # NONCE CHECK
    expected_nonce = compute_nonces(chain).get(sender, 0)

    if tx.get("nonce") != expected_nonce:
        return {"ok": False, "error": f"Invalid nonce. Expected {expected_nonce}"}

    # BASIC ACTION CHECK
    if tx.get("action") not in ("transfer", "add_liquidity"):
        return {"ok": False, "error": "Unsupported action"}

    # ADD TO MEMPOOL
    added = mempool.add(tx)
    if not added:
        return {"ok": False, "error": "TX already in mempool"}

    return {
        "ok": True,
        "sender": sender,
        "txid": tx["txid"]
    }

@app.post("/tx/mint")
async def send_mint_tx(payload: dict):
    mempool = Mempool()
    storage = ChainStorage()

    chain = storage.load()
    protocol = get_protocol(chain)

    tx = payload["tx"]
    tx["action"] = "mint_bridge"
    signature = payload["signature"]

    # Build canonical payload
    signed_payload = {
        key: tx[key]
        for key in ("txid", "action", "asset", "amount", "to", "nonce", "chainId")
        if key in tx
    }

    message = canonical_tx(signed_payload)

    try:
        recovered = Account.recover_message(
            encode_defunct(text=message),
            signature=signature
        )
    except Exception:
        return {"ok": False, "error": "Invalid signature format"}

    sender = recovered.lower()

    # Only protocol-defined bridge issuer
    if sender != protocol["bridge_issuer"].lower():
        return {"ok": False, "error": "Unauthorized mint issuer"}

    # chainId check
    if tx.get("chainId") != protocol["chain_id"]:
        return {"ok": False, "error": "Invalid chainId"}

    # asset check
    native = protocol["native_asset"]

    if tx.get("asset") == native:
        return {"ok": False, "error": "Bridge cannot mint native asset"}

    if tx.get("asset") not in protocol["allowed_assets"]:
        return {"ok": False, "error": "Unsupported asset"}

    # amount check
    if tx.get("amount", 0) <= 0:
        return {"ok": False, "error": "Invalid amount"}

    if not is_canonical_amount(tx["amount"]):
        return {"ok": False, "error": "Non canonical amount"}

    # nonce check
    expected_nonce = compute_nonces(chain).get(sender, 0)

    if tx.get("nonce") != expected_nonce:
        return {"ok": False, "error": f"Invalid nonce. Expected {expected_nonce}"}

    # Complete tx
    tx["sender"] = sender.lower()
    tx["timestamp"] = int(time.time())

    tx["_meta"] = {
        "sender": sender,
        "signature": signature,
        "received_at": int(time.time()),
        "type": "bridge_mint"
    }

    if "to" in tx:
        tx["to"] = tx["to"].lower()

    # Add to mempool
    added = mempool.add(tx)

    if not added:
        return {"ok": False, "error": "TX already in mempool"}

    return {
        "ok": True,
        "issuer": sender,
        "txid": tx["txid"]
    }

@app.get("/pools")
def get_pools():
    chain = storage.load()
    chain = [Block.from_dict(b) for b in chain]
    return compute_pools(chain)

@app.get("/market/stats")
def get_market_stats():
    chain = storage.load()

    protocol = get_protocol(chain)
    
    if not chain:
        return {
            "price_usd": 0,
            "total_supply": 0,
            "treasury": 0,
            "circulating_supply": 0,
            "market_cap": 0,
            "fully_diluted_valuation": 0,
            "pool_liquidity_usd": 0
        }
    
    balances = compute_balances(chain, protocol)
    native = protocol["native_asset"]
    treasury_addr = protocol["treasury"].lower()

    # Sum all native-asset balances across all addresses (including pools)
    total_supply = sum(
        v for key, v in balances.items()
        if key.endswith(f":{native}") and v > 0
    )
    treasury = balances.get(f"{treasury_addr}:{native}", 0)
    circulating_supply = total_supply - treasury
    
    # Find pools
    pools = chain[-1].get("pools", [])
    main_pool = next((p for p in pools if p["id"] == "aUSD-ARGH"), None)
    
    if main_pool:
        price_usd = main_pool["reserve0"] / main_pool["reserve1"]
        pool_liquidity = main_pool["reserve0"] * 2
    else:
        price_usd = 0
        pool_liquidity = 0
    
    return {
        "price_usd": round(price_usd, 6),
        "total_supply": total_supply,
        "treasury": treasury,
        "circulating_supply": circulating_supply,
        "market_cap": round(circulating_supply * price_usd, 2),
        "fully_diluted_valuation": round(total_supply * price_usd, 2),
        "pool_liquidity_usd": pool_liquidity
    }

@app.get("/tx/history/{address}")
def tx_history(address: str):
    address = norm(address)
    chain = storage.load()

    txs = []

    for block in chain:
        raw_block_time = block.get("block_time")
        block_ts = iso_to_ts(raw_block_time) if raw_block_time else 0
        
        block_idx = block.get("index")
        producer = norm(block.get("producer_id"))

        for tx in block.get("transactions", []):
            if not tx_involves_address(tx, address):
                continue

            asset = tx.get("asset")
            fee = tx.get("_fee", {}).get("total", 0)

            sender = norm(tx.get("sender"))
            to = norm(tx.get("to"))

            ts = tx.get("timestamp")

            if isinstance(ts, str):
                ts = iso_to_ts(ts)
            elif ts is None:
                ts = block_ts

            entry = {
                "txid": tx.get("txid"),
                "action": tx.get("action"),
                "asset": asset,
                "amount": tx.get("amount"),
                "fee": fee,
                "fee_asset": "ARGH",
                "from": sender,
                "to": to,
                "timestamp": ts,
                "block": block_idx,
                "confirmed": True
            }

            # whoever spends sees the total
            if sender == address:
                entry["total_spent"] = {
                    asset: tx.get("amount", 0),
                    "ARGH": fee
                }

            txs.append(entry)

    txs.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "address": address,
        "count": len(txs),
        "txs": txs
    }

@app.get("/tx/pending/{address}")
def tx_pending(address: str):
    address = norm(address)
    mempool = Mempool()
    storage = ChainStorage()

    chain = storage.load()
    protocol = get_protocol(chain)
    native = protocol["native_asset"]

    txs = []

    for tx in mempool.load():
        if not tx_involves_address(tx, address):
            continue

        fee = tx.get("_fee", {}).get("total")

        if fee is None and tx.get("action") == "transfer":
            fee = TransactionEngine.calculate_fee(
                tx["amount"], protocol
            )["total"]
        else:
            fee = fee or 0

        sender = norm(tx.get("sender"))
        to = norm(tx.get("to"))

        entry = {
            "txid": tx.get("txid"),
            "action": tx.get("action"),
            "asset": tx.get("asset"),
            "amount": tx.get("amount"),
            "fee": fee,
            "fee_asset": native,
            "from": sender,
            "to": to,
            "timestamp": tx.get("timestamp", 0),
            "confirmed": False
        }

        if sender == address:
            entry["total_spent"] = {
                tx.get("asset"): tx.get("amount", 0),
                native: fee
            }

        txs.append(entry)

    txs.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "address": address,
        "count": len(txs),
        "txs": txs
    }


@app.get("/tx/all/{address}")
def tx_all(address: str):
    address = norm(address)

    confirmed = tx_history(address)["txs"]
    pending = tx_pending(address)["txs"]

    return {
        "address": address,
        "pending": pending,
        "confirmed": confirmed
    }

@app.get("/auth/challenge")
def create_challenge():
    now = int(time.time())

    # Prune expired or used challenges to prevent unbounded growth
    expired = [k for k, v in challenges.items() if v["used"] or now - v["created_at"] > CHALLENGE_TTL]
    for k in expired:
        del challenges[k]

    cid = str(uuid.uuid4())

    message = f"""SolarChain Login
    Challenge: {cid}
    Timestamp: {now}
    """

    challenges[cid] = {
        "message": message,
        "used": False,
        "created_at": now,
    }

    return {
        "challenge_id": cid,
        "message": message
    }

@app.post("/auth/verify")
def verify(payload: dict):
    cid = payload["challenge_id"]
    signature = payload["signature"]
    address = payload["address"]

    challenge = challenges.get(cid)
    if not challenge or challenge["used"]:
        return {"ok": False}

    if int(time.time()) - challenge["created_at"] > CHALLENGE_TTL:
        del challenges[cid]
        return {"ok": False}

    msg = encode_defunct(text=challenge["message"])
    recovered = Account.recover_message(msg, signature=signature)

    if recovered.lower() != address.lower():
        return {"ok": False}

    challenge["used"] = True
    return {"ok": True}

@app.get("/balance/{address}")
def get_balance(address: str):
    address = norm(address)
    chain = storage.load()

    protocol = get_protocol(chain)
    if not protocol:
        raise ValueError("Missing protocol state")

    from core.state import compute_balances

    balances = compute_balances(chain, protocol)
    user_balances = {}

    for key, value in balances.items():
        if ":" not in key:
            continue

        addr, asset = key.rsplit(":", 1)

        if addr.lower() == address:
            user_balances[asset] = value

    return {
        "address": address,
        "balances": user_balances
    }