import time
from core.block import Block
from core.utils import norm, q

def generate(chain, p2p, storage):

  if not chain and not p2p.peers:
    print("Creating GENESIS block (this is the first node)")

    genesis_tx = [
        {
            "action": "mint",
            "amount": q(550_000),
            "asset": "ARGH",
            "sender": "0x000000000000000000000000000000xARGH",
            "to": "0x000000000000000000000000000000xARGH",
            "nonce": 0,
            "chainId": 1,
            "timestamp": int(time.time()),
        },
        {
            "action": "mint",
            "amount": q(5_000),
            "asset": "aUSD",
            "sender": "0x000000000000000000000000000000xARGH",
            "to": "0x000000000000000000000000000000xARGH",
            "nonce": 1,
            "chainId": 1,
            "timestamp": int(time.time()),
        },
        {
            "action": "transfer",
            "amount": q(25_000),
            "asset": "ARGH",
            "sender": "0x000000000000000000000000000000xARGH",
            "to": norm("0xE357a324ACbE736c66A2C669ff8999aE79Ff22c5"),
            "nonce": 2,
            "chainId": 1,
            "timestamp": 0,
        },
        {
            "action": "transfer",
            "amount": q(25_000),
            "asset": "ARGH",
            "sender": "0x000000000000000000000000000000xARGH",
            "to": norm("0x344a144698E0BEBdd9A27CE4B93b13AFff5D623F"),
            "nonce": 3,
            "chainId": 1,
            "timestamp": int(time.time()),
        },
        {
            "action": "add_liquidity",
            "pool_id": "aUSD-ARGH",    
            "asset": "ARGH",
            "asset_paired": "aUSD",
            "amount": q(500_000),
            "amount_paired": q(5_000),
            "sender": "0x000000000000000000000000000000xARGH",
            "nonce": 4,
            "chainId": 1,
            "txid": "genesis-pool-liquidity",
            "timestamp": int(time.time()),
        },
    ]

    _protocol_params = {
        "treasury": "0x000000000000000000000000000000xARGH",
        "devs": "0x000000000000000000000000000000DEVS",
        "orbital": "0x000000000000000000000000000000ORBITAL",
        "bridge_issuer": "0xd79Ee7A4143BBFF5316647C1d4b0B7461e4eb448",
        "version": 1,
        "chain_id": 1,
        "soft_cap": "12000000",
        "mint_scale": "0.08",
        "flux_scale": "1000000000000000000",
        "flux_normalizer": "10000000",
        "geomag_scale": "1000000",
        "transfer_fee_percent": "0.005",
        "fee_distribution": {
            "devs": "0.25",
            "orbital": "0.25",
            "validator": "0.50"
        },
        "allowed_assets": ["ARGH", "aUSD"],
        "native_asset": "ARGH",
        "min_stake": "1000",
        "slot_duration": 60,
        "oracle": {
            "pubkeys": [
                "db8469661f0e6d01664b9759e7dbfb2f289e658e13c04e6418dbb9a27005d524"
            ],
            "threshold": 1
        }
    }

    genesis_block = Block(
        index=0,
        prev_hash="0" * 64,
        transactions=genesis_tx,
        slot=0,
        flare_commit=None,
        producer_id="0x0000000000000000000000000000000000000000",
        protocol=_protocol_params
    )

    chain.append(genesis_block)
    storage.save(chain)

  elif not chain and p2p.peers:
    print("Waiting for peers")