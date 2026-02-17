# core/state.py

from config.settings import TREASURY_ADDRESS
from core.tx_engine import TransactionEngine
from core.utils import is_system_tx

def compute_balances(chain):
    """Calcola i balance finali dalla chain"""
    balances = {}
    tx_engine = TransactionEngine()
    
    for block_data in chain:
        block = block_data if isinstance(block_data, dict) else block_data.to_dict()
        validator = block.get("producer_id")
        
        for tx in block.get("transactions", []):            
            tx_engine.apply_tx(
                balances,
                tx,
                system=is_system_tx(tx),
                validator_address=validator
            )
    
    return balances

def compute_spendable_balances(chain, pending_txs):
    """Calcola balance spendibili (chain + mempool)"""
    balances = compute_balances(chain)
    tx_engine = TransactionEngine()
    
    
    for tx in pending_txs:
        tx_engine.apply_tx(
            balances,
            tx,
            system=is_system_tx(tx),
            validator_address=None
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

    for block_data in chain:
        block = block_data if isinstance(block_data, dict) else block_data.to_dict()

        for tx in block.get("transactions", []):
            sender = tx.get("sender")
            if not sender:
                continue

            if is_system_tx(tx):
                continue

            nonces[sender] = nonces.get(sender, 0) + 1

    return nonces
