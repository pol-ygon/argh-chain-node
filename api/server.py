from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import BRIDGE_ISSUER_ADDRESS, DEVS_ADDRESS, ORBITAL_ADDRESS, TREASURY_ADDRESS
from core.block import Block
from core.mempool import Mempool
from core.state import compute_pools
from core.storage import ChainStorage
from core.tx_engine import TransactionEngine
from core.utils import canonical_tx

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
    
    # Calculate the Treasury balance
    balances = {}
    for block in chain:
        for tx in block.get("transactions", []):
            action = tx.get("action")
            amount = tx.get("amount", 0)
            sender = tx.get("sender", "").lower()
            to = tx.get("to", "").lower()
            
            if action == "mint":
                balances[to] = balances.get(to, 0) + amount
            elif action == "transfer":
                fee = tx.get("_fee", {})
                balances[TREASURY_ADDRESS.lower()] = (
                    balances.get(TREASURY_ADDRESS.lower(), 0)
                    + fee.get("devs", 0)
                    + fee.get("orbital", 0)
                )
            elif action == "burn":
                balances[sender] = balances.get(sender, 0) - amount
            elif action == "add_liquidity":
                balances[sender] = balances.get(sender, 0) - amount
    
    treasury_balance = balances.get(TREASURY_ADDRESS.lower(), 0)
    
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

    tx = payload["tx"]
    signature = payload["signature"]

    # signed payload (MUST match canonical_tx)
    signed_payload = {
        key: tx[key]
        for key in ("txid", "action", "asset", "amount", "to", "nonce", "chainId")
        if key in tx
    }

    message = canonical_tx(signed_payload)
    print("BACKEND MESSAGE:", message)

    recovered = Account.recover_message(
        encode_defunct(text=message),
        signature=signature
    )

    sender = recovered.lower()
    print("BACKEND RECOVERED:", sender)

    # complete the tx
    tx["sender"] = sender
    tx["timestamp"] = int(time.time())

    tx["_meta"] = {
        "sender": sender,
        "signature": signature,
        "received_at": int(time.time()),
    }

    if "to" in tx:
        tx["to"] = tx["to"].lower()

    # basic validations
    if tx.get("action") == "transfer" and not tx.get("to"):
        return {"ok": False, "error": "Missing recipient"}

    if tx.get("amount", 0) <= 0:
        return {"ok": False, "error": "Invalid amount"}

    if not tx.get("asset"):
        return {"ok": False, "error": "Missing asset"}

    print("TX RECEIVED:", tx)

    added = mempool.add(tx)
    if not added:
        return {"ok": False, "error": "TX already in mempool"}

    return {
        "ok": True,
        "sender": sender,
        "txid": tx["txid"],
        "gossiped": added
    }

@app.post("/tx/mint")
async def send_mint_tx(payload: dict):
    mempool = Mempool()

    tx = payload["tx"]
    tx["action"] = "mint_bridge"
    signature = payload["signature"]

    # Build canonical payload for signature verification
    signed_payload = {
        key: tx[key]
        for key in ("txid", "action", "asset", "amount", "to", "nonce", "chainId")
        if key in tx
    }

    message = canonical_tx(signed_payload)
    print("MINT MESSAGE:", message)

    try:
        recovered = Account.recover_message(
            encode_defunct(text=message),
            signature=signature
        )
    except Exception:
        print("Invalid signature format")
        return {"ok": False, "error": "Invalid signature format"}

    sender = recovered.lower()
    print("RECOVERED:", sender)

    # Only issuer can mint
    if sender != BRIDGE_ISSUER_ADDRESS.lower():
        print("Unauthorized mint issuer")
        return {"ok": False, "error": "Unauthorized mint issuer"}

    # Complete the tx
    tx["sender"] = sender
    tx["timestamp"] = int(time.time())

    tx["_meta"] = {
        "sender": sender,
        "signature": signature,
        "received_at": int(time.time()),
        "type": "bridge_mint"
    }

    if "to" in tx:
        tx["to"] = tx["to"].lower()

    # Mint specific validations
    if tx.get("action") != "mint_bridge":
        print("Invalid action")
        return {"ok": False, "error": "Invalid action"}

    if tx.get("asset") != "aUSD":
        print("Invalid asset")
        return {"ok": False, "error": "Invalid asset"}

    if tx.get("amount", 0) <= 0:
        print("Invalid amount")
        return {"ok": False, "error": "Invalid amount"}

    print("MINT TX RECEIVED:", tx)

    added = mempool.add(tx)
    
    if not added:
        print("TX already in mempool")
        return {"ok": False, "error": "TX already in mempool"}

    return {
        "ok": True,
        "issuer": sender,
        "txid": tx["txid"],
        "gossiped": added
    }


@app.get("/pools")
def get_pools():
    chain = storage.load()
    chain = [Block.from_dict(b) for b in chain]
    return compute_pools(chain)

@app.get("/market/stats")
def get_market_stats():
    chain = storage.load()
    
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
    
    # Calculate all balances
    balances = {}
    for block in chain:
        for tx in block.get("transactions", []):
            action = tx.get("action")
            amount = tx.get("amount", 0)
            sender = tx.get("sender", "").lower()
            to = tx.get("to", "").lower()
            
            if action == "mint":
                balances[to] = balances.get(to, 0) + amount
            elif action == "transfer":
                fee = tx.get("_fee", {})
                fee_total = fee.get("total", 0)

                balances[sender] = balances.get(sender, 0) - amount - fee_total
                balances[to] = balances.get(to, 0) + amount

                # fee split
                balances[TREASURY_ADDRESS.lower()] = (
                    balances.get(TREASURY_ADDRESS.lower(), 0)
                    + fee.get("devs", 0)
                    + fee.get("orbital", 0)
                )

                producer = block.get("producer_id", "").lower()
                balances[producer] = balances.get(producer, 0) + fee.get("validator", 0)
            elif action == "burn":
                balances[sender] = balances.get(sender, 0) - amount
            elif action == "add_liquidity":
                balances[sender] = balances.get(sender, 0) - amount
                # Also tracks pool balance
                pool_address = f"pool:{tx.get('pool_id', '')}".lower()
                balances[pool_address] = balances.get(pool_address, 0) + amount
    
    # ✅ Treasury = balance of TREASURY_ADDRESS
    treasury = balances.get(TREASURY_ADDRESS.lower(), 0)
    
    # Total supply = sum of all balances
    total_supply = sum(balances.values())
    
    # Circulating = total - treasury
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

    txs = []

    for tx in mempool.load():
        if not tx_involves_address(tx, address):
            continue

        asset = tx.get("asset")

        fee = tx.get("_fee", {}).get("total")
        if fee is None and tx.get("action") == "transfer":
            fee = TransactionEngine.calculate_fee(tx["amount"])["total"]
        else:
            fee = fee or 0

        sender = norm(tx.get("sender"))
        to = norm(tx.get("to"))

        entry = {
            "txid": tx.get("txid"),
            "action": tx.get("action"),
            "asset": asset,
            "amount": tx.get("amount"),
            "fee": fee,
            "fee_asset": "ARGH",
            "from": sender,
            "to": to,
            "timestamp": tx.get("timestamp", 0),
            "confirmed": False
        }

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
    cid = str(uuid.uuid4())

    message = f"""SolarChain Login
    Challenge: {cid}
    Timestamp: {int(time.time())}
    """

    challenges[cid] = {
        "message": message,
        "used": False
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

    balances = {}

    def add(asset, value):
        balances[asset] = balances.get(asset, 0) + value

    for block in chain:
        producer = norm(block.get("producer_id"))

        for tx in block.get("transactions", []):
            action = tx.get("action")
            asset = tx.get("asset")
            amount = tx.get("amount", 0)

            raw_sender = tx.get("sender")
            raw_to = tx.get("to")

            sender = norm(raw_sender) if raw_sender and raw_sender.startswith("0x") else raw_sender
            to = norm(raw_to) if raw_to and raw_to.startswith("0x") else raw_to

            fee = tx.get("_fee", {})

            if action == "transfer":
                if sender == address:
                    add(asset, -amount)
                if to == address:
                    add(asset, amount)

                if fee:
                    if sender == address:
                        add("ARGH", -fee.get("total", 0))
                    if address == DEVS_ADDRESS:
                        add("ARGH", fee.get("devs", 0))
                    if address == ORBITAL_ADDRESS:
                        add("ARGH", fee.get("orbital", 0))
                    if address == producer:
                        add("ARGH", fee.get("validator", 0))

            elif action in ("mint", "mint_bridge"):
                if to == address:
                    add(asset, amount)

            elif action == "burn":
                if sender == address:
                    add(asset, -amount)

            elif action == "add_liquidity":
                if sender == address:
                    add(asset, -tx["amount"])
                    add(tx["asset_paired"], -tx["amount_paired"])

            elif action == "reward":
                if to == address:
                    add(asset, amount)

    return {
        "address": address,
        "balances": balances
    }
