# core/pool_engine.py

from copy import deepcopy

class PoolEngine:

    @staticmethod
    def apply_swap(tx: dict, pools: list) -> list:
        """
        Apply an AMM (constant product) swap and
        return a NEW pool list
        """
        pools = deepcopy(pools)

        pool_id = tx["pool_id"]
        amount_in = tx["amount_in"]
        min_out = tx.get("min_out", 0)
        token_in = tx["token_in"]

        pool = next((p for p in pools if p["id"] == pool_id), None)
        if not pool:
            raise ValueError("Pool not found")

        # 🔁 determines swap direction
        if token_in == pool["token0"]:
            x_key, y_key = "reserve0", "reserve1"
        elif token_in == pool["token1"]:
            x_key, y_key = "reserve1", "reserve0"
        else:
            raise ValueError("Invalid token_in")

        x = pool[x_key]
        y = pool[y_key]

        fee = pool.get("fee", 0)
        dx = int(amount_in * (1 - fee))

        # constant product
        k = x * y
        new_x = x + dx
        new_y = k // new_x

        dy = y - new_y
        if dy <= 0:
            raise ValueError("Invalid swap output")

        if dy < min_out:
            raise ValueError("Slippage exceeded")

        # Update pool
        pool[x_key] = new_x
        pool[y_key] = new_y

        return pools
