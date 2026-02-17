# core/block_validator
from config.settings import TREASURY_ADDRESS
from core.consensus import select_block_producer
from core.treasury import TreasuryEngine
from core.tx_engine import TransactionEngine
from core.validator_keystore import verify_block_signature
from core.state import compute_balances


class BlockValidator:
    def __init__(self, validators, validator_pubkeys, chain):
        self.validators = validators
        self.validator_pubkeys = validator_pubkeys
        self.chain = chain
        self.tx_engine = TransactionEngine()

    def validate(self, block, prev_block, chain_until_prev):
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
        # 3. flare sanity
        # --------------------------------------------------
        if block.flare_time is None:
            print(f"❌ Invalid flare_time (1)")
            return False

        if block.flare_time > block.block_time:
            print(f"❌ Invalid flare_time (2)")
            return False

        # --------------------------------------------------
        # 4. hash
        # --------------------------------------------------
        if block.compute_hash() != block.hash:
            print(f"❌ Invalid Hash")
            return False

        # --------------------------------------------------
        # 5. treasury validation
        # --------------------------------------------------

        # Rebuild balances up to prev_block
        balances = compute_balances(chain_until_prev)
        treasury_balance = balances.get(TREASURY_ADDRESS, 0)

        # Recalculate expected delta
        # GENESIS has no flare → skips treasury validation
        if block.index == 0:
            return True

        if block.flare_id is None:
            print(f"❌ Invalid Block: missing flare_id")
            return False

        prev_block_flare_id = prev_block.flare_id if prev_block else None

        if block.flare_id == prev_block_flare_id:
            # Same flare as previous block → no system TX expected
            expected_action = None
            expected_delta = 0
        else:
            expected_delta, expected_action = TreasuryEngine.compute_delta(
                block.flare_flux,
                block.flare_class,
                block.geomag_factor,
                treasury_balance
            )
        # Extract mint/burn from the block
        system_txs = [
            tx for tx in block.transactions
            if tx.get("action") in ("mint", "burn")
        ]

        if expected_action is None:
            if system_txs:
                print(f"❌ Invalid TX (1)")
                return False
        else:
            if len(system_txs) != 1:
                print(f"❌ Invalid TX (2)")
                return False

            tx = system_txs[0]

            if tx["action"] != expected_action:
                print(f"❌ Invalid TX: unexpected action")
                return False

            if tx["amount"] != expected_delta:
                print(f"❌ Invalid TX: unexpected amount")
                return False
            

        for tx in block.transactions:
            is_system = tx.get("action") in ("mint", "burn", "reward")
            try:
                self.tx_engine.validate(tx, balances, system=is_system)
                self.tx_engine.apply_tx(balances, tx, system=is_system)
            except ValueError as e:
                print(f"❌ Invalid TX during block validation: {e}")
                return False

        # --------------------------------------------------
        # 6. Leader
        # --------------------------------------------------
        expected_leader = select_block_producer(
            last_block_flare_data=prev_block.get_flare_seed(),
            validators=self.validators,
            last_block_hash=prev_block.hash,
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
