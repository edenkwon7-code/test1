"""
UserAuth.py — 다중 사용자 인증 유틸리티
════════════════════════════════════════
PBKDF2-HMAC-SHA256 기반 비밀번호 해싱.
외부 라이브러리 없이 Python 표준 라이브러리만 사용.

보안 수준:
  - 솔트: 32바이트 CSPRNG (os.urandom)
  - 반복 횟수: 260,000회 (OWASP 2023 권고)
  - 저장 형식: "iterations:b64(salt):b64(hash)"
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from base64 import b64decode, b64encode


ITERATIONS = 260_000
HASH_ALG   = "sha256"
SALT_BYTES = 32


def hash_password(raw: str) -> str:
    """비밀번호 → 저장 가능한 해시 문자열 반환"""
    salt  = os.urandom(SALT_BYTES)
    dk    = hashlib.pbkdf2_hmac(HASH_ALG, raw.encode(), salt, ITERATIONS)
    return f"{ITERATIONS}:{b64encode(salt).decode()}:{b64encode(dk).decode()}"


def verify_password(raw: str, stored: str) -> bool:
    """입력 비밀번호와 저장된 해시 비교 (타이밍 안전)"""
    try:
        iterations, b64_salt, b64_hash = stored.split(":", 2)
        salt      = b64decode(b64_salt)
        old_hash  = b64decode(b64_hash)
        new_hash  = hashlib.pbkdf2_hmac(
            HASH_ALG, raw.encode(), salt, int(iterations)
        )
        return hmac.compare_digest(old_hash, new_hash)
    except Exception:
        return False


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def validate_password(pw: str) -> tuple[bool, str]:
    """비밀번호 정책 검증. Returns (ok, reason)"""
    if len(pw) < 8:
        return False, "비밀번호는 최소 8자 이상이어야 합니다."
    if not any(c.isdigit() for c in pw):
        return False, "숫자를 최소 1개 포함해야 합니다."
    return True, ""


def generate_session_token() -> str:
    """세션 토큰 생성 (64 hex chars)"""
    return secrets.token_hex(32)
