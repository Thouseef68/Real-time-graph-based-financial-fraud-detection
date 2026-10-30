"""Authentication and authorization module with JWT tokens and local demo users.

Provides roles:
- "analyst": standard review/action workflows (ground truth hidden)
- "admin": full access including settings modification and demo_reveal flag
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import os
from pathlib import Path
import secrets

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"

def _ensure_env_credentials() -> Dict[str, str]:
    """Ensures .env exists with randomly generated secure credentials if not present."""
    creds = {
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "",
        "ANALYST_USERNAME": "analyst",
        "ANALYST_PASSWORD": "",
        "SECRET_KEY": "",
    }
    
    if ENV_PATH.exists():
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        creds[k.strip()] = v.strip()
        except Exception:
            pass

    # Generate random credentials if missing
    changed = False
    if not creds.get("ADMIN_PASSWORD"):
        creds["ADMIN_PASSWORD"] = secrets.token_urlsafe(16)
        changed = True
    if not creds.get("ANALYST_PASSWORD"):
        creds["ANALYST_PASSWORD"] = secrets.token_urlsafe(16)
        changed = True
    if not creds.get("SECRET_KEY"):
        creds["SECRET_KEY"] = secrets.token_hex(32)
        changed = True

    if changed and not ENV_PATH.exists():
        try:
            with open(ENV_PATH, "w", encoding="utf-8") as f:
                f.write(f"# Auto-generated FraudEngine environment credentials\n")
                for k, v in creds.items():
                    f.write(f"{k}={v}\n")
        except Exception:
            pass

    return creds

_creds = _ensure_env_credentials()
SECRET_KEY = os.getenv("SECRET_KEY", _creds.get("SECRET_KEY", "fraudengine-secure-key-default"))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 3600 * 24  # 24 hours

_admin_user = os.getenv("ADMIN_USERNAME", _creds.get("ADMIN_USERNAME", "admin"))
_admin_pass = os.getenv("ADMIN_PASSWORD", _creds.get("ADMIN_PASSWORD", "admin_secure"))
_analyst_user = os.getenv("ANALYST_USERNAME", _creds.get("ANALYST_USERNAME", "analyst"))
_analyst_pass = os.getenv("ANALYST_PASSWORD", _creds.get("ANALYST_PASSWORD", "analyst_secure"))

DEMO_USERS: Dict[str, Dict[str, Any]] = {
    _analyst_user: {
        "username": _analyst_user,
        "password_hash": hashlib.sha256(_analyst_pass.encode()).hexdigest(),
        "role": "analyst",
        "email": "analyst@fraudengine.local",
    },
    _admin_user: {
        "username": _admin_user,
        "password_hash": hashlib.sha256(_admin_pass.encode()).hexdigest(),
        "role": "admin",
        "email": "admin@fraudengine.local",
    },
}

security = HTTPBearer(auto_error=False)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = len(s) % 4
    if pad:
        s += "=" * (4 - pad)
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def create_access_token(data: Dict[str, Any], expires_delta: Optional[int] = None) -> str:
    """Create a tamper-evident HMAC-SHA256 JWT."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    exp = now + (expires_delta or ACCESS_TOKEN_EXPIRE_SECONDS)
    payload = {**data, "iat": now, "exp": exp}

    h_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h_b64}.{p_b64}".encode()
    signature = hmac.new(SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
    s_b64 = _b64url_encode(signature)
    return f"{h_b64}.{p_b64}.{s_b64}"


def decode_access_token(token: str) -> Dict[str, Any]:
    """Verify and decode a JWT."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
        )
    h_b64, p_b64, s_b64 = parts
    signing_input = f"{h_b64}.{p_b64}".encode()
    expected_sig = hmac.new(SECRET_KEY.encode(), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(s_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signature verification failed",
        )

    payload = json.loads(_b64url_decode(p_b64).decode())
    if payload.get("exp", 0) < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    return payload


def verify_password(plain_password: str, password_hash: str) -> bool:
    candidate_hash = hashlib.sha256(plain_password.encode()).hexdigest()
    return hmac.compare_digest(candidate_hash, password_hash)


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    user = DEMO_USERS.get(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Dict[str, Any]:
    """Dependency for authenticated endpoints; falls back to demo analyst if no token provided in local dev."""
    if not credentials:
        # Fallback to local demo analyst in development
        return DEMO_USERS["analyst"]
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        if username not in DEMO_USERS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User no longer exists",
            )
        return DEMO_USERS[username]
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )


async def require_admin(
    user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privilege required",
        )
    return user
