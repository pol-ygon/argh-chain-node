# core/validator_keystore

from cryptography.fernet import Fernet
from pathlib import Path
from nacl.signing import SigningKey
from nacl.encoding import RawEncoder
from hashlib import sha256

from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

DATA_DIR = Path("data")
FERNET_KEY_FILE = DATA_DIR / "validator.node.key"
VALIDATOR_KEY_FILE = DATA_DIR / "validator.key"
ENV_FILE = Path(".env")

def load_or_create_fernet_key():
    if FERNET_KEY_FILE.exists():
        return FERNET_KEY_FILE.read_bytes()

    DATA_DIR.mkdir(exist_ok=True)
    key = Fernet.generate_key()
    FERNET_KEY_FILE.write_bytes(key)
    return key

def load_or_create_validator_key():
    fernet = Fernet(load_or_create_fernet_key())

    if VALIDATOR_KEY_FILE.exists():
        encrypted = VALIDATOR_KEY_FILE.read_bytes()
        raw = fernet.decrypt(encrypted)
        return SigningKey(raw, encoder=RawEncoder)

    sk = SigningKey.generate()
    encrypted = fernet.encrypt(sk.encode(encoder=RawEncoder))
    VALIDATOR_KEY_FILE.write_bytes(encrypted)
    return sk

def pubkey_to_address(pubkey_bytes: bytes) -> str:
    digest = sha256(pubkey_bytes).digest()
    return "0x" + digest[-20:].hex()

def write_env_address(address: str):
    if ENV_FILE.exists():
        content = ENV_FILE.read_text()
        if "NODE_ADDRESS=" in content:
            return

    with ENV_FILE.open("a") as f:
        f.write(f"\nNODE_ADDRESS={address}\n")

def verify_block_signature(block, validator_pubkeys: dict) -> bool:
    """
    validator_pubkeys: { address -> pubkey_bytes }
    """
    try:
        address = block.producer_id.lower()
        pubkey = validator_pubkeys.get(address)

        if not pubkey:
            return False

        vk = VerifyKey(pubkey, encoder=RawEncoder)

        vk.verify(
            block.hash.encode(),
            bytes.fromhex(block.signature)
        )
        return True

    except BadSignatureError:
        return False
