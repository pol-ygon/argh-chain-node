import requests
from typing import Optional
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError
from core.utils import canonical_json

# 👇 endpoint oracle
ORACLE_URL = "https://flare-oracle.argh.space/flare/"

# 👇 chiave pubblica oracle (hex)
ORACLE_PUBKEY = "db8469661f0e6d01664b9759e7dbfb2f289e658e13c04e6418dbb9a27005d524"


class FlareSource:
    """
    Blockchain-side flare source.
    NON calcola nulla.
    Verifica solo firma oracle.
    """

    def __init__(self):
        self.verify_key = VerifyKey(bytes.fromhex(ORACLE_PUBKEY))

    # --------------------------------------------------
    # PUBLIC ENTRYPOINT
    # --------------------------------------------------

    def get_flare_for_slot(self, slot: int) -> Optional[dict]:
        """
        Recupera flare dallo slot specificato.
        Verifica firma oracle.
        Deterministico.
        """

        try:
            response = requests.get(f"{ORACLE_URL}{slot}", timeout=3)

            if response.status_code != 200:
                return None

            data = response.json()

            # verifica slot coerente
            if data.get("slot") != slot:
                return None

            if not self._verify_oracle_signature(data):
                print("❌ Invalid oracle signature")
                return None

            # ritorna solo dati consensus-critical
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
        """
        Verifica firma ED25519 oracle.
        """

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

            self.verify_key.verify(message, signature)

            return True

        except BadSignatureError:
            return False
        except Exception:
            return False
