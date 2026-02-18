# core/treasury.py
from decimal import Decimal, getcontext
from core.utils import q

class TreasuryEngine:
    @staticmethod
    def compute_delta(flare_flux, flare_class, geomag_factor, treasury_balance, params):
        getcontext().prec = 50
        flare_flux = Decimal(flare_flux) / Decimal(params["flux_scale"])
        geomag_factor = Decimal(geomag_factor) / Decimal(params["geomag_scale"])
        treasury_balance = Decimal(treasury_balance)

        normalizer = Decimal(params["flux_normalizer"])
        base = (flare_flux * normalizer).sqrt()

        intensity = abs(geomag_factor)

        mint_scale = Decimal(params["mint_scale"])
        soft_cap = Decimal(params["soft_cap"])

        if flare_class in ("A", "B", "C"):
            delta = base * intensity * mint_scale
            action = "mint"

        elif flare_class == "M":
            burn = max(base * intensity * mint_scale, treasury_balance / Decimal(6))
            delta = burn
            action = "burn"

        elif flare_class == "X":
            burn = max(base * intensity * mint_scale, treasury_balance / Decimal(3))
            delta = burn
            action = "burn"

        else:
            return Decimal(0), None

        # Soft cap amplifier
        if treasury_balance > soft_cap and action == "burn":
            delta = delta * Decimal("1.5")

        if action == "burn":
            delta = min(delta, treasury_balance)

        return q(delta), action