import requests
from typing import Optional
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from config.settings import ORACLE_URL
from core.utils import canonical_json
class FlareSource:
    """
    Blockchain-side flare source.
    Does not compute anything.
    Only verifies the oracle signature.
    """

    def __init__(self, protocol):
        self.protocol = protocol
        self.pubkeys = protocol["oracle"]["pubkeys"]
        self.threshold = protocol["oracle"]["threshold"]

    # --------------------------------------------------
    # PUBLIC ENTRYPOINT
    # --------------------------------------------------

    def get_flare_for_slot(self, slot: int) -> Optional[dict]:
        """
        Fetches flare data for the specified slot.
        Verifies oracle signature.
        Deterministic.
        """

        try:
            response = requests.get(f"{ORACLE_URL}{slot}", timeout=3)

            if response.status_code != 200:
                return None

            data = response.json()

            # verify slot coherence
            if data.get("slot") != slot:
                return None

            if not self._verify_oracle_signature(data):
                print("Invalid oracle signature")
                return None

            # return only consensus-critical data
            return {
                "id": data["id"],
                "slot": data["slot"],
                "flux": int(data["flux"]),
                "class": data["class"],
                "geomag": int(data["geomag"]),
                "oracle_signature": data["oracle_signature"],
            }

        except Exception as e:
            print("FlareSource error:", e)
            return None

    # --------------------------------------------------
    # SIGNATURE VERIFICATION
    # --------------------------------------------------

    def _verify_oracle_signature(self, data: dict) -> bool:
        try:
            signature = bytes.fromhex(data["oracle_signature"])

            payload = {
                "id": data["id"],
                "slot": data["slot"],
                "class": data["class"],
                "flux": data["flux"],
                "geomag": data["geomag"],
            }

            message = canonical_json(payload)

            valid_sigs = 0

            for pk in self.pubkeys:
                try:
                    verify_key = VerifyKey(bytes.fromhex(pk))
                    verify_key.verify(message, signature)
                    valid_sigs += 1
                except BadSignatureError:
                    continue

            return valid_sigs >= self.threshold

        except Exception:
            return False
