# core/consensus.py

import hashlib
from typing import Dict, List

def select_block_producer(
    validators: List[str],
    last_block_hash: str,
    slot: int,
    attempt: int = 0,
) -> str:

    if not validators:
        raise ValueError("Validator set empty")

    seed_material = f"{last_block_hash}|{slot}|{attempt}"
    seed = hashlib.sha256(seed_material.encode()).hexdigest()

    best_node = None
    best_score = None

    for node_id in validators:
        score = hashlib.sha256(
            f"{seed}|{node_id}".encode()
        ).hexdigest()

        if best_score is None or score < best_score:
            best_score = score
            best_node = node_id

    return best_node