import base64, hashlib, hmac, json, os, secrets, time
from cryptography.fernet import Fernet

def _fernet():
    key = os.getenv("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required")
    return Fernet(key.encode())

def encrypt_token(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def decrypt_token(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()

def create_oauth_state(user_id: str) -> str:
    secret = os.getenv("OAUTH_STATE_SECRET")
    if not secret:
        raise RuntimeError("OAUTH_STATE_SECRET is required")
    payload = {"user_id": user_id, "nonce": secrets.token_urlsafe(18), "exp": int(time.time()) + 600}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"

def verify_oauth_state(state: str) -> str:
    secret = os.getenv("OAUTH_STATE_SECRET")
    if not secret or "." not in state:
        raise ValueError("Invalid OAuth state")
    body, sig = state.rsplit(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid OAuth state signature")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("OAuth state expired")
    return payload["user_id"]
