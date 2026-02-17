# core/treasury.py
import math
from config.settings import SOFT_CAP, MINT_SCALE, TREASURY_ADDRESS
from core.utils import q


class TreasuryEngine:
    @staticmethod
    def compute_delta(flare_flux, flare_class, geomag_factor, treasury_balance):

        base = (flare_flux / 1e-8) ** 0.5
        intensity = abs(geomag_factor)

        if flare_class in ("A", "B", "C"):
            delta = q(base * intensity * MINT_SCALE)
            action = "mint"

        elif flare_class == "M":
            burn = max(base * intensity * MINT_SCALE, treasury_balance / 6)
            delta = q(burn)
            action = "burn"

        elif flare_class == "X":
            burn = max(base * intensity * MINT_SCALE, treasury_balance / 3)
            delta = q(burn)
            action = "burn"

        else:
            delta = 0
            action = None

        if treasury_balance > SOFT_CAP and action == "burn":
            delta = q(delta * 1.5)

        if action == "burn":
            delta = min(delta, treasury_balance)

        return delta, action
