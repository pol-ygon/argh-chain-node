# core/state.py

from core.tx_engine import TransactionEngine
from core.utils import get_protocol, is_system_tx

def compute_balances(chain, protocol):
    """Compute final balances from the chain"""
    balances = {}
    tx_engine = TransactionEngine()
    
    for block_data in chain:
        block = block_data if isinstance(block_data, dict) else block_data.to_dict()
        validator = block.get("producer_id")
        
        for tx in block.get("transactions", []):

            # Skip non-economic transactions
            if tx.get("action") == "flare_reveal":
                continue

            tx_engine.apply_tx(
                balances,
                tx,
                system=is_system_tx(tx, protocol),
                validator_address=validator,
                protocol=protocol
            )
    
    return balances


def compute_spendable_balances(chain, pending_txs, protocol):
    """Compute spendable balances (chain + mempool)"""
    balances = compute_balances(chain, protocol)
    tx_engine = TransactionEngine()
    
    
    for tx in pending_txs:
        tx_engine.apply_tx(
            balances,
            tx,
            system=is_system_tx(tx, protocol),
            validator_address=None,
            protocol=protocol
        )
    
    return balances

def compute_pools(chain):
    pools = {}

    for block_data in chain:
        block = block_data if isinstance(block_data, dict) else block_data.to_dict()

        for tx in block.get("transactions", []):
            action = tx.get("action")

            if action == "add_liquidity":
                pid = tx["pool_id"]

                if pid not in pools:
                    pools[pid] = {
                        "id": pid,
                        "token0": tx["asset_paired"],
                        "token1": tx["asset"],
                        "reserve0": 0,
                        "reserve1": 0,
                        "fee": 0.003,
                        "amm": "constant_product",
                    }

                pools[pid]["reserve0"] += tx["amount_paired"]
                pools[pid]["reserve1"] += tx["amount"]

            #elif action == "swap":
            #    pid = tx["pool_id"]
            #    pools[pid] = PoolEngine.apply_swap(tx, pools[pid])

    return list(pools.values())

def compute_nonces(chain):
    nonces = {}

    protocol = get_protocol(chain)

    for block_data in chain:
        block = block_data if isinstance(block_data, dict) else block_data.to_dict()

        for tx in block.get("transactions", []):
            sender = tx.get("sender")
            if not sender:
                continue

            if is_system_tx(tx, protocol):
                continue

            nonces[sender] = nonces.get(sender, 0) + 1

    return nonces
