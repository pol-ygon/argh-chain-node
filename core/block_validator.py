# core/block_validator
import hashlib
from core.consensus import select_block_producer
from core.flare_source import FlareSource
from core.treasury import TreasuryEngine
from core.tx_engine import TransactionEngine
from core.utils import canonical_json, get_protocol, q
from core.validator_keystore import verify_block_signature
from core.state import compute_balances

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError


class BlockValidator:
    def __init__(self, validators, validator_pubkeys, chain):
        self.validators = validators
        self.validator_pubkeys = validator_pubkeys
        self.chain = chain
        self.tx_engine = TransactionEngine()

    def verify_oracle_signature(self, payload: dict, protocol: dict) -> bool:
        try:
            pubkeys = protocol["oracle"]["pubkeys"]

            message_payload = {
                "id": payload["id"],
                "slot": payload["slot"],
                "class": payload["class"],
                "flux": payload["flux"],
                "geomag": payload["geomag"],
            }

            message = canonical_json(message_payload)
            signature = bytes.fromhex(payload["oracle_signature"])

            valid_count = 0

            for pk in pubkeys:
                verify_key = VerifyKey(bytes.fromhex(pk))
                try:
                    verify_key.verify(message, signature)
                    valid_count += 1
                except BadSignatureError:
                    continue

            return valid_count >= protocol["oracle"]["threshold"]

        except Exception:
            return False

    def validate(self, block, prev_block, chain_until_prev, mode="live"):

        # --------------------------------------------------
        # 1. Basic structure
        # --------------------------------------------------
        if not isinstance(block.index, int):
            print("Invalid: block.index must be int")
            return False

        if not isinstance(block.transactions, list):
            print("Invalid: block.transactions must be list")
            return False

        if not hasattr(block, "slot"):
            print("Invalid: block missing 'slot'")
            return False

        # --------------------------------------------------
        # GENESIS
        # --------------------------------------------------
        if block.index == 0:
            if not block.protocol:
                print("Genesis missing protocol")
                return False
            if block.prev_hash != "0" * 64:
                print("Invalid prev_hash")
                return False
            if block.slot != 0:
                print("Invalid slot")
                return False
            if block.hash != block.compute_hash():
                print("Invalid hash")
                return False
            if block.signature is not None:
                print("Invalid signature")
                return False
            return True

        protocol = get_protocol(chain_until_prev)
        if not protocol:
            print("Missing protocol state")
            return False

        # --------------------------------------------------
        # 2. Continuity
        # --------------------------------------------------
        if prev_block is None:
            print("Invalid: prev_block is None")
            return False

        if block.index != prev_block.index + 1:
            print("Invalid index")
            return False

        if block.prev_hash != prev_block.hash:
            print("Invalid prev_hash")
            return False

        if block.slot <= prev_block.slot:
            print("Invalid slot")
            return False

        # --------------------------------------------------
        # 4. Hash
        # --------------------------------------------------
        if block.compute_hash() != block.hash:
            print("Invalid hash")
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
                    print("Multiple flare_reveal TX")
                    return False

                reveal_tx = flare_reveal_txs[0]
                payload = reveal_tx["payload"]

                # ------------------------------------------------
                # 1. Verify commit
                # ------------------------------------------------

                raw = canonical_json(payload)
                actual_commit = hashlib.sha256(raw).hexdigest()

                if actual_commit != prev_block.flare_commit:
                    print("Commit mismatch")
                    return False

                # ------------------------------------------------
                # 2. Verify oracle signature
                # ------------------------------------------------

                if not self.verify_oracle_signature(payload, protocol):
                    print("Invalid oracle signature")
                    return False

                # ------------------------------------------------
                # 3. Verify slot coherence
                # ------------------------------------------------

                expected_slot = prev_block.slot
                print(f"expected -> prev_block.slot: {str(prev_block.slot)}")
                print(f"payload slot: {str(payload.get('slot'))}")

                if payload.get("slot") != expected_slot:
                    print("Oracle slot mismatch")
                    return False

        # --------------------------------------------------
        # 5. Treasury validation (commit/reveal model)
        # --------------------------------------------------

        balances = compute_balances(chain_until_prev, protocol)
        treasury_address = protocol["treasury"]
        native_asset = protocol["native_asset"]
        treasury_balance = balances.get(f"{treasury_address}:{native_asset}", 0)

        expected_action = None
        expected_delta = 0

        # Find flare_reveal TX in the current block
        reveal_txs = [
            tx for tx in block.transactions
            if tx.get("action") == "flare_reveal"
        ]

        if reveal_txs:
            if len(reveal_txs) != 1:
                print("Multiple flare_reveal TX")
                return False

            reveal_tx = reveal_txs[0]

            # sender must be the producer of the previous block
            if reveal_tx["sender"] != prev_block.producer_id:
                print("Reveal sender mismatch")
                return False

            payload = reveal_tx["payload"]

            # Verify commit
            raw = canonical_json(payload)

            actual_commit = hashlib.sha256(raw).hexdigest()

            if actual_commit != prev_block.flare_commit:
                print("Reveal commit mismatch")
                return False

            # Compute delta
            expected_delta, expected_action = TreasuryEngine.compute_delta(
                payload["flux"],
                payload["class"],
                payload["geomag"],
                treasury_balance,
                protocol
            )

        # Check mint/burn
        system_txs = [
            tx for tx in block.transactions
            if tx.get("action") in ("mint", "burn")
        ]

        if expected_action is None:
            if system_txs:
                print("Unexpected system TX")
                return False
        else:
            if len(system_txs) != 1:
                print("Missing system TX")
                return False

            tx = system_txs[0]

            if tx["action"] != expected_action:
                print("Wrong action")
                return False

            if q(tx["amount"]) != expected_delta:
                print("Wrong amount")
                return False

        # --------------------------------------------------
        # 6. Leader
        # --------------------------------------------------

        attempt = getattr(block, "attempt", 0)
        expected_leader = select_block_producer(
            validators=self.validators,
            last_block_hash=prev_block.hash,
            slot=block.slot,
            attempt=attempt
        )
        if block.producer_id != expected_leader:
            print(f"Unauthorized producer (attempt={attempt})")
            return False

        # --------------------------------------------------
        # 7. Block signature
        # --------------------------------------------------
        if not block.signature:
            return False

        if not verify_block_signature(block, self.validator_pubkeys):
            return False

        return True