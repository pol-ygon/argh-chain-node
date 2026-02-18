# core/block_validator
import hashlib
from core.consensus import select_block_producer
from core.flare_source import FlareSource
from core.treasury import TreasuryEngine
from core.tx_engine import TransactionEngine
from core.utils import canonical_json, get_protocol
from core.validator_keystore import verify_block_signature
from core.state import compute_balances


class BlockValidator:
    def __init__(self, validators, validator_pubkeys, chain):
        self.validators = validators
        self.validator_pubkeys = validator_pubkeys
        self.chain = chain
        self.tx_engine = TransactionEngine()

    def validate(self, block, prev_block, chain_until_prev, mode="live"):

        # --------------------------------------------------
        # 1. basic structure
        # --------------------------------------------------
        if not isinstance(block.index, int):
            print(f"❌ Invalid isinstance(block.index, int)")
            return False

        if not isinstance(block.transactions, list):
            print(f"❌ Invalid isinstance(block.transactions, list)")
            return False

        if not hasattr(block, "slot"):
            print(f"❌ Invalid hasattr(block, 'slot')")
            return False

        # --------------------------------------------------
        # 🧱 GENESIS
        # --------------------------------------------------
        if block.index == 0:
            if not block.protocol:
                print("❌ Genesis missing protocol")
                return False
            if block.prev_hash != "0" * 64:
                print(f"❌ Invalid prev_hash")
                return False
            if block.slot != 0:
                print(f"❌ Invalid slot")
                return False
            if block.hash != block.compute_hash():
                print(f"❌ Invalid hash")
                return False
            if block.signature is not None:
                print(f"❌ Invalid signature")
                return False
            return True
        
        protocol = get_protocol(chain_until_prev)
        if not protocol:
            print("❌ Missing protocol state")
            return False

        # --------------------------------------------------
        # 2. continuity
        # --------------------------------------------------
        if prev_block is None:
            print(f"❌ Invalid prev_block is none")
            return False

        if block.index != prev_block.index + 1:
            print(f"❌ Invalid index")
            return False

        if block.prev_hash != prev_block.hash:
            print(f"❌ Invalid prev_hash != hash")
            return False

        if block.slot <= prev_block.slot:
            print(f"❌ Invalid slot")
            return False

        # --------------------------------------------------
        # 4. hash
        # --------------------------------------------------
        if block.compute_hash() != block.hash:
            print(f"❌ Invalid Hash")
            return False
        
        # --------------------------------------------------
        # FLARE REVEAL VERIFICATION (API deterministic)
        # --------------------------------------------------

        if mode == "live":
            flare_reveal_txs = [
                tx for tx in block.transactions
                if tx.get("action") == "flare_reveal"
            ]

            if flare_reveal_txs:

                if len(flare_reveal_txs) != 1:
                    print("❌ Multiple flare_reveal TX")
                    return False

                reveal_tx = flare_reveal_txs[0]
                payload = reveal_tx["payload"]

                raw = canonical_json(payload)
                actual_commit = hashlib.sha256(raw).hexdigest()

                if actual_commit != prev_block.flare_commit:
                    print("❌ Commit mismatch")
                    return False

                flare_source = FlareSource()
                expected_flare = flare_source.get_flare_for_slot(
                    prev_block.slot - 1
                )

                if not expected_flare:
                    print("❌ Cannot fetch flare for verification")
                    return False

                print(expected_flare["flux"])
                print(payload["flux"])
                
                print(expected_flare["geomag"])
                print(payload["geomag"])

                flux_scaled = expected_flare["flux"]
                geomag_scaled = expected_flare["geomag"]

                # 🔒 3️⃣ Compare values
                if payload["flux"] != flux_scaled:
                    print("❌ Flux mismatch")
                    return False

                if payload["class"] != expected_flare["class"]:
                    print("❌ Class mismatch")
                    return False

                if payload["geomag"] != geomag_scaled:
                    print("❌ Geomag mismatch")
                    return False

        # --------------------------------------------------
        # 5. treasury validation (commit/reveal model)
        # --------------------------------------------------

        balances = compute_balances(chain_until_prev, protocol)
        treasury_address = protocol["treasury"]
        treasury_balance = balances.get(f"{treasury_address}:ARGH", 0)

        expected_action = None
        expected_delta = 0

        # Cerca flare_reveal TX nel blocco corrente
        reveal_txs = [
            tx for tx in block.transactions
            if tx.get("action") == "flare_reveal"
        ]

        if reveal_txs:
            if len(reveal_txs) != 1:
                print("❌ Multiple flare_reveal TX")
                return False

            reveal_tx = reveal_txs[0]

            # sender deve essere producer del blocco precedente
            if reveal_tx["sender"] != prev_block.producer_id:
                print("❌ Reveal sender mismatch")
                return False

            payload = reveal_tx["payload"]

            # verifica commit
            raw = canonical_json(payload)

            actual_commit = hashlib.sha256(raw).hexdigest()

            if actual_commit != prev_block.flare_commit:
                print("❌ Reveal commit mismatch")
                return False

            # Calcola delta
            expected_delta, expected_action = TreasuryEngine.compute_delta(
                payload["flux"],
                payload["class"],
                payload["geomag"],
                treasury_balance,
                protocol
            )

        # Controlla mint/burn
        system_txs = [
            tx for tx in block.transactions
            if tx.get("action") in ("mint", "burn")
        ]

        if expected_action is None:
            if system_txs:
                print("❌ Unexpected system TX")
                return False
        else:
            if len(system_txs) != 1:
                print("❌ Missing system TX")
                return False

            tx = system_txs[0]

            if tx["action"] != expected_action:
                print("❌ Wrong action")
                return False

            if tx["amount"] != expected_delta:
                print("❌ Wrong amount")
                return False

        # --------------------------------------------------
        # 6. Leader
        # --------------------------------------------------
        expected_leader = select_block_producer(
            validators=self.validators,
            last_block_hash=prev_block.hash,
            slot=block.slot
        )

        if block.producer_id != expected_leader:
            return False

        # --------------------------------------------------
        # 7. Sign Block
        # --------------------------------------------------
        if not block.signature:
            return False

        if not verify_block_signature(block, self.validator_pubkeys):
            return False

        return True
