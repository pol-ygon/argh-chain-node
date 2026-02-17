# core/consensus.py

import hashlib
from typing import Dict, List

def select_block_producer(
    last_block_flare_data: Dict,
    validators: List[str],
    last_block_hash: str,
) -> str:
    """
    Deterministically selects the slot leader
    using ONLY on-chain data (last block).
    """

    if not validators:
        raise ValueError("Validator set empty")

    seed_material = (
        f"{last_block_flare_data.get('time_tag', '')}"
        f"|{last_block_flare_data.get('satellite', 18)}"
        f"|{last_block_flare_data.get('flux', 0.0):.12e}"
        f"|{last_block_flare_data.get('observed_flux', 0.0):.12e}"
        f"|{last_block_flare_data.get('electron_correction', 0.0):.12e}"
        f"|{last_block_flare_data.get('energy', '0.05-0.4nm')}"
        f"|{last_block_hash}"
    )

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
