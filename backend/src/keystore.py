"""
Secure storage for the TwelveLabs API key.

Principle: an API key is a live credential, not a password — it must be usable,
so we ENCRYPT it (reversible), we do not hash it (one-way). At rest it is
Fernet-encrypted with a machine-local secret; it is decrypted only in-process to
make TwelveLabs calls and is never returned to the client (the UI only ever sees
a masked preview).

  * the encrypted ciphertext lives in the settings table (db.py)
  * the Fernet secret lives in backend/.secret_key (gitignored), generated once
  * in production this secret comes from a KMS / secret manager, not a file
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from . import db

_SECRET_FILE = Path(__file__).resolve().parent.parent / ".secret_key"
_KEY_SETTING = "tl_api_key_enc"
_INDEX_SETTING = "tl_index_id"


def _fernet() -> Fernet:
    if not _SECRET_FILE.exists():
        _SECRET_FILE.write_bytes(Fernet.generate_key())
        _SECRET_FILE.chmod(0o600)
    return Fernet(_SECRET_FILE.read_bytes())


def save_key(api_key: str) -> None:
    db.set_setting(_KEY_SETTING, _fernet().encrypt(api_key.encode()).decode())


def get_key() -> Optional[str]:
    enc = db.get_setting(_KEY_SETTING)
    if not enc:
        return None
    try:
        return _fernet().decrypt(enc.encode()).decode()
    except Exception:
        return None  # secret rotated or corrupt ciphertext -> treat as no key


def clear_key() -> None:
    db.set_setting(_KEY_SETTING, None)


def masked() -> Optional[str]:
    k = get_key()
    if not k:
        return None
    return (k[:4] + "•" * 8 + k[-4:]) if len(k) > 8 else "•" * 8


def is_connected() -> bool:
    return get_key() is not None


# Which TwelveLabs index videos are uploaded into (created on demand, see indexes.py).
def get_index_id() -> Optional[str]:
    return db.get_setting(_INDEX_SETTING)


def set_index_id(index_id: str) -> None:
    db.set_setting(_INDEX_SETTING, index_id)
