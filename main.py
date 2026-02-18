# main.py
from datetime import datetime
import hashlib
import json
import secrets
import sys
import time
import uuid

from core import genesis
from core.block_validator import BlockValidator
from core.tx_engine import TransactionEngine
from core.mempool import Mempool
from core.flare_source import FlareSource
from core.transaction import Transaction
from core.treasury import TreasuryEngine
from core.block import Block
from core.storage import ChainStorage
from core.state import compute_balances, compute_spendable_balances
from config.settings import  HOST_IP, HOST_PORT
from core.network import P2PNetwork
from core.consensus import select_block_producer

import asyncio

from core.utils import canonical_json, get_protocol, norm, q, loading, load_validators
from core.validator_keystore import load_or_create_validator_key, pubkey_to_address, write_env_address
from core.validator_keystore import load_or_create_validator_key

# -----------------------------
# TIME SLOT CONFIGURATION
# -----------------------------
SLOT_TOLERANCE = 5  # 5 second window to produce the block
BLOCK_PROPAGATION_WAIT = 5  # seconds to wait to receive blocks from other nodes
# -----------------------------

PROTOCOL_SENDER = "_protocol"

def make_reward(to, amount, protocol):
    return {
        "action": "reward",
        "asset": protocol["native_asset"],
        "amount": q(amount),
        "sender": PROTOCOL_SENDER.lower(),
        "txid": str(uuid.uuid4()),
        "to": to.lower(),
        "chainId": protocol["chain_id"],
        "timestamp": int(time.time()),
    }

def get_current_slot(protocol):
    """Returns the current time slot"""
    return int(time.time() // protocol["slot_duration"])

def get_slot_start_time(slot, protocol):
    """Returns the start timestamp of the slot"""
    return slot * protocol["slot_duration"]

def is_valid_block_time(block_slot, protocol):
    current_time = time.time()
    slot_start = get_slot_start_time(block_slot, protocol)
    slot_end = slot_start + SLOT_TOLERANCE
    return slot_start <= current_time <= slot_end

# -----------------------------
# CHAIN Validation
# -----------------------------
def validate_chain(chain, validator):
    for i, block in enumerate(chain):
        prev = chain[i - 1] if i > 0 else None
        chain_until_prev = chain[:i]
        if not validator.validate(block, prev, chain_until_prev, mode="sync"):
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

async def handle_reveal(
    parent_block,
    parent_chain,
    current_slot,
    tx_engine,
    user_txs,
    protocol
):
    system_txs = []
    reveal_tx = None

    if not parent_block.flare_commit:
        return system_txs, None

    for tx in user_txs:
        if (
            tx.get("action") == "flare_reveal"
            and tx.get("commit") == parent_block.flare_commit
            and tx.get("sender") == parent_block.producer_id
        ):
            reveal_tx = tx
            break

    if not reveal_tx:
        return system_txs, None

    payload = reveal_tx["payload"]

    raw = canonical_json(payload)
    actual_commit = hashlib.sha256(raw).hexdigest()

    if actual_commit != parent_block.flare_commit:
        raise ValueError("Reveal commit mismatch")

    print("✅ Valid flare reveal TX detected")

    flux = payload["flux"]
    flare_cls = payload["class"]
    geomag_factor = payload["geomag"]

    balances_before = await asyncio.to_thread(
        compute_balances,
        parent_chain,
        protocol
    )

    treasury_address = protocol["treasury"]
    native_asset = protocol["native_asset"]

    treasury_balance = balances_before.get(
        f"{treasury_address}:{native_asset}",
        0
    )


    delta, action = TreasuryEngine.compute_delta(
        flux,
        flare_cls,
        geomag_factor,
        treasury_balance,
        protocol
    )

    print(f"💰 Reveal Δ: {delta:+,} ({action})")

    if action and q(delta) > 0:
        system_tx = Transaction(
            sender=treasury_address,
            to=treasury_address,
            action=action,
            amount=q(delta),
            nonce=1,
            timestamp=get_slot_start_time(parent_block.slot + 1, protocol),
            chainId=protocol["chain_id"],
            asset=native_asset
        ).to_dict()

        system_tx["_fee"] = {
            "total": 0,
            "devs": 0,
            "orbital": 0,
            "validator": 0
        }

        tx_engine.validate(system_tx, balances_before, protocol, system=True)
        system_txs.append(system_tx)

    return system_txs, reveal_tx

async def handle_commit(flare_source, current_slot):
    previous_slot = current_slot - 1

    # 🔒 flare deterministico per slot
    flare_data = flare_source.get_flare_for_slot(previous_slot)

    if not flare_data:
        return None, None

    # 🔒 secret NON deve influenzare consenso
    secret = secrets.token_hex(16)

    reveal_payload = {
        "id": flare_data["id"],
        "flux": flare_data["flux"],
        "class": flare_data["class"],
        "geomag": flare_data["geomag"],
        "secret": secret
    }

    raw = canonical_json(reveal_payload)

    flare_commit = hashlib.sha256(raw).hexdigest()

    return flare_commit, reveal_payload

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

    protocol = get_protocol(chain)
    if not protocol:
        raise ValueError("Missing protocol state")

    last_processed_slot = get_current_slot(protocol) - 1

    asyncio.create_task(mempool_gossip_loop(p2p, mempool))
    asyncio.create_task(p2p.heartbeat())

    # -----------------------------
    # Loop
    # -----------------------------
    while True:
        await asyncio.sleep(0)

        if not chain:
            print("⏳ Chain is empty, waiting for the genesis...")
            await asyncio.sleep(1)
            continue

        protocol = get_protocol(chain)
        if not protocol:
            raise ValueError("Missing protocol state")
        current_slot = get_current_slot(protocol)

        if chain[-1].slot == current_slot:
          last_processed_slot = current_slot
          continue


                
        # ✅ Skipping if this slot is already processed
        if current_slot == last_processed_slot:
            await asyncio.sleep(1)
            continue
        
        # ✅ Calculate the wainting time until next slot
        current_time = time.time()
        slot_start = get_slot_start_time(current_slot, protocol)
        
        # If you are not in the slot, just wait
        if current_time < slot_start:
            wait_time = slot_start - current_time
            slot_timestamp = datetime.fromtimestamp(slot_start).strftime('%H:%M:%S')
            print(f"⏰ Waiting --> #{current_slot} ({slot_timestamp}) - {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
            current_time = time.time()
        
        # ✅ Verify that you are in the right time window
        if not is_valid_block_time(current_slot, protocol):
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
            validators=VALIDATORS,
            last_block_hash=parent_block.hash,
            slot=current_slot
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

        # =====================================================
        # 1️⃣ REVEAL PHASE (valida blocco precedente)
        # =====================================================

        user_txs = mempool.load()

        system_txs, reveal_tx =  await handle_reveal(
            parent_block,
            parent_chain,
            current_slot,
            tx_engine,
            user_txs,
            protocol
        )

        # =====================================================
        # 3️⃣ USER TX PROCESSING
        # =====================================================

        user_txs = mempool.load()
        user_txs = sorted(user_txs, key=lambda x: x["txid"])

        valid_user_txs = []
        spendable_balances = compute_spendable_balances(parent_chain, [], protocol)
        invalid_txids = set()

        for i, tx in enumerate(user_txs):
            if i % 10 == 0:
                await asyncio.sleep(0)

            if tx.get("action") == "flare_reveal":
                continue   # viene validata nella fase reveal

            try:
                tx_engine.validate(tx, spendable_balances, protocol)

                txc = dict(tx)

                if txc["action"] == "transfer":
                    txc["_fee"] = TransactionEngine.calculate_fee(txc["amount"], protocol)
                else:
                    txc["_fee"] = {
                        "total": 0,
                        "devs": 0,
                        "orbital": 0,
                        "validator": 0
                    }

                valid_user_txs.append(txc)

                tx_engine.apply_tx(
                    spendable_balances,
                    txc,
                    system=False,
                    validator_address=None,
                    protocol=protocol
                )

            except ValueError as e:
                print(f"❌ DISCARDED: {e}")
                invalid_txids.add(tx["txid"])

        if reveal_tx:
            valid_user_txs.append(reveal_tx)

        print(f"📝 Processed TX: {len(valid_user_txs)} user + {len(system_txs)} system")

        # =====================================================
        # 4️⃣ FEES
        # =====================================================

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
            reward_tx = make_reward(protocol["devs"], fee_totals["devs"], protocol)
            tx_engine.validate(reward_tx, spendable_balances, protocol, system=True)
            system_txs.append(reward_tx)

        if fee_totals["orbital"] > 0:
            reward_tx = make_reward(protocol["orbital"], fee_totals["orbital"], protocol)
            tx_engine.validate(reward_tx, spendable_balances, protocol, system=True)
            system_txs.append(reward_tx)
        
        if fee_totals["validator"] > 0:
            reward_tx = make_reward(NODE_ADDRESS, fee_totals["validator"], protocol)
            tx_engine.validate(reward_tx, spendable_balances, protocol, system=True)
            system_txs.append(reward_tx)

        # =====================================================
        # 5️⃣ BLOCK CREATION
        # =====================================================

        txs = valid_user_txs + system_txs

        flare_commit = None
        new_reveal = None

        flare_commit, new_reveal = await handle_commit(
            flare_source,
            current_slot
        )

        block = Block(
            index=len(chain),
            prev_hash=parent_block.hash,
            transactions=txs,
            slot=current_slot,
            flare_commit=flare_commit,
            producer_id=NODE_ADDRESS,
        )

        block.signature = SIGNING_KEY.sign(
            block.hash.encode()
        ).signature.hex()

        chain.append(block)
        await asyncio.to_thread(storage.save, chain)

        # =====================================================
        # 6️⃣ CLEAN MEMPOOL
        # =====================================================

        included_txids = {tx["txid"] for tx in valid_user_txs}
        mempool.remove_many(included_txids | invalid_txids)

        print(f"⛓️ Block #{block.index} created")
        print(f"   Hash: {block.hash[:16]}...")
        print("="*70)

        # =====================================================
        # 7️⃣ BROADCAST
        # =====================================================

        await p2p.broadcast({
            "type": "block",
            "data": block.to_dict()
        })

        print("📡 Block sent to P2P network")

        # DOPO broadcast del blocco
        if new_reveal and flare_commit:

            reveal_tx = {
                "action": "flare_reveal",
                "payload": new_reveal,
                "commit": flare_commit,
                "sender": NODE_ADDRESS,
                "nonce": uuid.uuid4().hex,
                "chainId": protocol["chain_id"],
                "timestamp": int(time.time()),
                "txid": uuid.uuid4().hex,
            }

            reveal_tx["signature"] = SIGNING_KEY.sign(
                canonical_json(reveal_tx)
            ).signature.hex()

            mempool.add(reveal_tx)

            await p2p.broadcast({
                "type": "tx",
                "data": reveal_tx
            })

            print("📤 Flare reveal TX broadcasted")


        last_processed_slot = current_slot
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