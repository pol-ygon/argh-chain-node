# main.py
from datetime import datetime
import json
import sys
import time
import uuid

from core import genesis
from core.block_validator import BlockValidator
from core.tx_engine import TransactionEngine
from core.mempool import Mempool
from core.flare_source import FlareSource
from core.flare_detector import FlareDetector
from core.transaction import Transaction
from core.treasury import TreasuryEngine
from core.block import Block
from core.storage import ChainStorage
from core.state import compute_balances, compute_pools, compute_spendable_balances
from config.settings import DEVS_ADDRESS, ORBITAL_ADDRESS, TREASURY_ADDRESS, HOST_IP, HOST_PORT
from core.network import P2PNetwork
from core.consensus import select_block_producer

import asyncio

from core.utils import norm, q, loading, load_validators
from core.validator_keystore import load_or_create_validator_key, pubkey_to_address, write_env_address
from core.validator_keystore import load_or_create_validator_key

# -----------------------------
# TIME SLOT CONFIGURATION
# -----------------------------
SLOT_DURATION = 60  # 1 block every 60 secs.
SLOT_TOLERANCE = 5  # 5 second window to produce the block
BLOCK_PROPAGATION_WAIT = 5  # seconds to wait to receive blocks from other nodes
# -----------------------------

PROTOCOL_SENDER = "_protocol"

def make_reward(to, amount):
    return {
        "action": "reward",
        "asset": "ARGH",
        "amount": q(amount),
        "sender": PROTOCOL_SENDER,
        "txid": str(uuid.uuid4()),
        "to": to,
        "chainId": 1,
        "timestamp": int(time.time()),
    }

def get_current_slot():
    """Returns the current time slot"""
    return int(time.time() // SLOT_DURATION)

def get_slot_start_time(slot):
    """Returns the start timestamp of the slot"""
    return slot * SLOT_DURATION

def is_valid_block_time(block_slot):
    """Check if we are at the right time to produce the block"""
    current_time = time.time()
    slot_start = get_slot_start_time(block_slot)
    slot_end = slot_start + SLOT_TOLERANCE
    return slot_start <= current_time <= slot_end

# -----------------------------
# CHAIN Validation
# -----------------------------
def validate_chain(chain, validator):
    for i, block in enumerate(chain):
        prev = chain[i - 1] if i > 0 else None
        chain_until_prev = chain[:i]
        if not validator.validate(block, prev, chain_until_prev):
            return False
    return True


# -----------------------------
# HELPERS
# -----------------------------

def bootstrap_validator():
    sk = load_or_create_validator_key()
    vk = sk.verify_key
    address = pubkey_to_address(vk.encode())

    write_env_address(address)

    return sk, address

# -----------------------------
# MAIN LOOP
# -----------------------------

async def main():
    SIGNING_KEY, NODE_ADDRESS = bootstrap_validator()

    #🔹Print Logo
    loading(NODE_ADDRESS)

    #🔹Load Validators
    VALIDATORS, VALIDATOR_PUBKEYS, nodes = load_validators()

    storage = ChainStorage()
    raw_chain = storage.load()
    chain = [Block.from_dict(b) for b in raw_chain] if raw_chain else []

    mempool = Mempool()
    tx_engine = TransactionEngine()
    flare_source = FlareSource()
    flare_detector = FlareDetector()

    validator = BlockValidator(
      validators=VALIDATORS,
      validator_pubkeys=VALIDATOR_PUBKEYS,
      chain=chain
    )

    #🔹Init. Peers
    MY_NODE_ID = NODE_ADDRESS
    p2p = P2PNetwork(
      MY_NODE_ID,
      chain,
      storage,
      validator,
      mempool=mempool
    )

    asyncio.create_task(p2p.connect_to_nodes(nodes))

    # Starting P2P Server
    server = await asyncio.start_server(
        p2p.handle_connection,
        HOST_IP,
        HOST_PORT
    )
    asyncio.create_task(server.serve_forever())
    await asyncio.sleep(3)

    #🔹Generate or Skip
    genesis.generate(chain, p2p, storage)

    #🔹Verifing Integrity
    if not validate_chain(chain, validator):
      print("❌ Blockchain is compromised, please clean ./data/chain.enc")
      sys.exit(1)
    print("✅ Blockchain is Valid")

    # ✅ TRACKING LAST PROCESSED SLOT
    last_processed_slot = get_current_slot() - 1

    asyncio.create_task(mempool_gossip_loop(p2p, mempool))
    asyncio.create_task(p2p.heartbeat())

    # -----------------------------
    # Loop
    # -----------------------------
    while True:
        await asyncio.sleep(0)
        current_slot = get_current_slot()

        if not chain:
            print("⏳ Chain is empty, waiting for the genesis...")
            await asyncio.sleep(1)
            continue

        if chain[-1].slot == current_slot:
          last_processed_slot = current_slot
          continue
                
        # ✅ Skipping if this slot is already processed
        if current_slot == last_processed_slot:
            await asyncio.sleep(1)
            continue
        
        # ✅ Calculate the wainting time until next slot
        current_time = time.time()
        slot_start = get_slot_start_time(current_slot)
        
        # If you are not in the slot, just wait
        if current_time < slot_start:
            wait_time = slot_start - current_time
            slot_timestamp = datetime.fromtimestamp(slot_start).strftime('%H:%M:%S')
            print(f"⏰ Waiting --> #{current_slot} ({slot_timestamp}) - {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
            current_time = time.time()
        
        # ✅ Verify that you are in the right time window
        if not is_valid_block_time(current_slot):
            # If it's too late for this slot, wait for the next one
            await asyncio.sleep(0.5)
            continue
        
        # ✅ Print the slot header
        print(f"\n{'='*70}")
        print(f"🕐 SLOT #{current_slot} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")


        if not chain:
            print("⏳ Chain still empty after reload, waiting for sync...")
            await asyncio.sleep(1)
            continue

        # ✅ EXTRACT SOLAR DATA FROM THE LAST BLOCK (DETERMINISTIC)

        parent_block = chain[-1]
        parent_chain = chain[:]   # snapshot BEFORE the new block

        last_block = chain[-1]
        last_block_dict = last_block.to_dict()

        # 🎯 Select leader
        leader = select_block_producer(
            last_block_flare_data=parent_block.get_flare_seed(),
            validators=VALIDATORS,
            last_block_hash=parent_block.hash,
        )
        
        print(f"👑 The leader for this slot is: {leader}")
        print(f"   (calculated by block #{last_block_dict.get('index')} hash {last_block_dict.get('hash', '')[:16]}...)")

        # ✅ I'm not the leader
        if leader.lower() != MY_NODE_ID.lower():
          print(f"⏭️ I'm not the leader, waiting the block from: {leader}")
          print(f"⏳ Waiting {BLOCK_PROPAGATION_WAIT}s for the propagation...")
          await asyncio.sleep(BLOCK_PROPAGATION_WAIT)
          continue
        
        print(f"▶️ I'm the leader for this slot!")

        # -----------------------------
        # ⚡ Call APIs only if you are a Leader
        # -----------------------------
        event = flare_source.get_latest()

        if event is None or not event.get("xray"):
            print("⚠️ No data from APIs, Skipping this Slot")
            last_processed_slot = current_slot
            await asyncio.sleep(1)
            continue

        flare = flare_detector.process(event["xray"])
        geomag_factor = event["geomag_factor"]

        if not flare:
            print("⚠️ No flare data, Skipping this Slot")
            last_processed_slot = current_slot
            await asyncio.sleep(1)
            continue

        # -----------------------------
        # SYSTEM TX (MINT / BURN)
        # -----------------------------
        system_txs = []

        balances_before = await asyncio.to_thread(
            compute_balances,
            parent_chain
        )
        
        treasury_balance = balances_before.get(
            f"{TREASURY_ADDRESS}:ARGH",
            0
        )

        delta = 0
        action = None
        if flare.id != parent_block.flare_id:
            delta, action = TreasuryEngine.compute_delta(
                flare.flux,
                flare.cls,
                geomag_factor,
                treasury_balance
            )

        print(f"🔥 Flare detected: {flare.id}")
        print(f"   Class: {flare.cls} | Flux: {flare.flux:.2e}")
        print(f"💰 Δ Calculations: {delta:+,} ({action})")

        # ✅ Create TX only if there is an action to be done
        slot_timestamp = get_slot_start_time(current_slot)

        if action and q(delta) > 0:
            system_tx = Transaction(
                sender=TREASURY_ADDRESS,
                to=TREASURY_ADDRESS,
                action=action,  # "mint" or "burn"
                amount=q(delta),
                nonce=1,
                timestamp=slot_timestamp,
                chainId=1,
                asset="ARGH"
            ).to_dict()
            
            system_tx["_fee"] = {
                "total": 0,
                "devs": 0,
                "orbital": 0,
                "validator": 0
            }

            # valid as system tx
            try:
                tx_engine.validate(system_tx, balances_before, system=True)
                system_txs.append(system_tx)
            except ValueError as e:
                print("❌ INVALID SYSTEM TX:", e)
        else:
            print("ℹ️ No system TX needed")

        # -----------------------------
        #  BLOCK PRODUCTION
        # -----------------------------
        user_txs = mempool.load()
        
        user_txs = sorted(user_txs, key=lambda x: x["txid"])
        valid_user_txs = []

        spendable_balances = compute_spendable_balances(parent_chain, [])
        invalid_txids = set()

        for i, tx in enumerate(user_txs):
            if i % 10 == 0:
                await asyncio.sleep(0)
            try:
                tx_engine.validate(tx, spendable_balances)

                # 🔥 CLONE the tx (DO NOT change the mempool)
                txc = dict(tx)

                if txc["action"] == "transfer":
                    txc["_fee"] = TransactionEngine.calculate_fee(txc["amount"])
                else:
                    txc["_fee"] = {
                        "total": 0,
                        "devs": 0,
                        "orbital": 0,
                        "validator": 0
                    }

                valid_user_txs.append(txc)

                # 🔁 Update spendable using apply_tx
                tx_engine.apply_tx(
                    spendable_balances,
                    txc,
                    system=False,
                    validator_address=None
                )

            except ValueError as e:
                print(f"❌ DISCARDED: {e} | action={tx.get('action')} | has_meta={'_meta' in tx} | nonce={tx.get('nonce')}")
                invalid_txids.add(tx["txid"])

        print(f"📝 Processed TX: {len(valid_user_txs)} user + {len(system_txs)} system")

        fee_totals = {
            "devs": 0,
            "orbital": 0,
            "validator": 0,
        }

        for tx in valid_user_txs:
            fee = tx.get("_fee")
            if not fee:
                continue

            fee_totals["devs"] += fee["devs"]
            fee_totals["orbital"] += fee["orbital"]
            fee_totals["validator"] += fee["validator"]

        if fee_totals["devs"] > 0:
            system_txs.append(make_reward(DEVS_ADDRESS, fee_totals["devs"]))

        if fee_totals["orbital"] > 0:
            system_txs.append(make_reward(ORBITAL_ADDRESS, fee_totals["orbital"]))

        if fee_totals["validator"] > 0:
            system_txs.append(make_reward(NODE_ADDRESS, fee_totals["validator"]))

        # -----------------------------
        # BLOCK CREATION
        # -----------------------------
        txs = valid_user_txs + system_txs

        if chain[-1].slot == current_slot:
          print("⚠️ Block already present for this slot, skip")
          last_processed_slot = current_slot
          continue

        block = Block(
            index=len(chain),
            prev_hash=parent_block.hash,
            flare=flare,
            geomag_factor=geomag_factor,
            transactions=txs,
            slot=current_slot,
            producer_id=NODE_ADDRESS,
        )

        block.signature = SIGNING_KEY.sign(
          block.hash.encode()
        ).signature.hex()
        

        chain.append(block)
        await asyncio.to_thread(storage.save, chain)


        # 🧹 remove only the included tx
        included_txids = {tx["txid"] for tx in valid_user_txs}
        # 🔥 removes both inclusions and rejections
        mempool.remove_many(included_txids | invalid_txids)

        block_hash = block.to_dict().get('hash')
        print(f"⛓️ Block #{block.index} created")
        print(f"   Hash: {block_hash[:16]}...")
        print(f"   Prev: {last_block_dict.get('hash', '')[:16]}...")
        print(f"{'='*70}\n")

        # 📡 BROADCAST OF THE BLOCK TO THE NETWORK
        await p2p.broadcast({
          "type": "block",
          "data": block.to_dict()
        })
        print("📡 Block sent to P2P network")

        # ✅ MARK THIS SLOT AS PROCESSED
        last_processed_slot = current_slot
        
        # Short break before the next check
        await asyncio.sleep(1)

async def mempool_gossip_loop(p2p, mempool):
    seen = set()

    while True:
        try:
            txs = mempool.load()

            for tx in txs:
                txid = tx["txid"]
                if txid in seen:
                    continue

                seen.add(txid)

                await p2p.broadcast({
                    "type": "tx",
                    "data": tx
                })

            if len(seen) > 10_000:
                seen.clear()

            await asyncio.sleep(2)

        except Exception as e:
            print("💥 GOSSIP LOOP CRASHED:", e)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())