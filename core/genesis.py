import time
from config.settings import TREASURY_ADDRESS
from core.block import Block
from core.utils import norm, q

def generate(chain, p2p, storage):

  if not chain and not p2p.peers:
    print("🧱 Creating GENESIS Block (I'm the first node)")

    genesis_tx = [
        {
            "action": "mint",
            "amount": q(550_000),
            "asset": "ARGH",
            "sender": TREASURY_ADDRESS,
            "to": TREASURY_ADDRESS,
            "nonce": 0,
            "chainId": 1,
            "timestamp": int(time.time()),
        },
        {
            "action": "mint",
            "amount": q(5_000),
            "asset": "aUSD",
            "sender": TREASURY_ADDRESS,
            "to": TREASURY_ADDRESS,
            "nonce": 1,
            "chainId": 1,
            "timestamp": int(time.time()),
        },
        {
            "action": "transfer",
            "amount": q(25_000),
            "asset": "ARGH",
            "sender": TREASURY_ADDRESS,
            "to": norm("0xE357a324ACbE736c66A2C669ff8999aE79Ff22c5"),
            "nonce": 2,
            "chainId": 1,
            "timestamp": 0,
        },
        {
            "action": "transfer",
            "amount": q(25_000),
            "asset": "ARGH",
            "sender": TREASURY_ADDRESS,
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
            "sender": TREASURY_ADDRESS,
            "nonce": 4,
            "chainId": 1,
            "txid": "genesis-pool-liquidity",
            "timestamp": int(time.time()),
        },
    ]

    genesis_block = Block(
        index=0,
        prev_hash="0" * 64,
        flare=None,
        geomag_factor=0,
        slot=0,
        transactions=genesis_tx,
    )

    chain.append(genesis_block)
    storage.save(chain)

  elif not chain and p2p.peers:
    print("⏳ Waiting for peers")