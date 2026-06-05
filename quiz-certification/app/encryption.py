"""AES-256-GCM encryption and decryption utilities for API payloads.

Secures sensitive quiz/answers payloads dynamically to prevent inspection via the network tab.
Supports both static keys and dynamic session-specific keys.
"""
import os
import json
import base64
import hashlib
from typing import Dict, Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config

# Derive static key from config secret
_raw_secret = config.APP_PAYLOAD_SECRET.encode('utf-8')
_STATIC_KEY = hashlib.sha256(_raw_secret).digest()  # Exactly 32 bytes


def get_key_bytes(key_source: Union[str, bytes] = None) -> bytes:
    """Hash the key source to ensure it is exactly 32 bytes."""
    if not key_source:
        return _STATIC_KEY
    if isinstance(key_source, str):
        key_source = key_source.encode('utf-8')
    return hashlib.sha256(key_source).digest()


def encrypt_payload(data: Union[Dict, list], key_source: Union[str, bytes] = None) -> Dict[str, str]:
    """Encrypt a dictionary or list to a base64 encoded AES-GCM payload."""
    serialized = json.dumps(data).encode('utf-8')
    key = get_key_bytes(key_source)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 12-byte nonce recommended for GCM
    
    # Returns combined ciphertext + tag
    ciphertext = aesgcm.encrypt(nonce, serialized, None)
    
    return {
        "nonce": base64.b64encode(nonce).decode('utf-8'),
        "ciphertext": base64.b64encode(ciphertext).decode('utf-8')
    }


def decrypt_payload(payload: Dict[str, str], key_source: Union[str, bytes] = None) -> Union[Dict, list]:
    """Decrypt an incoming base64 encoded AES-GCM payload."""
    if "nonce" not in payload or "ciphertext" not in payload:
        raise ValueError("Invalid encrypted payload format")
        
    nonce = base64.b64decode(payload["nonce"].encode('utf-8'))
    ciphertext = base64.b64decode(payload["ciphertext"].encode('utf-8'))
    
    key = get_key_bytes(key_source)
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(decrypted.decode('utf-8'))
