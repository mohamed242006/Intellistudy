"""Password hashing (Argon2id, contract JWT-10) and the password policy (JWT-11).

``verify_or_dummy`` always performs one Argon2 verification, also for unknown accounts, so a login attempt with an
unknown email costs the same time as one with a wrong password (JWT-12).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend.app.core.config import Settings

#: Common passwords that satisfy the length/letter/digit rules and must still be rejected (lower-case comparison).
#: A short built-in list; it can be extended without code changes to the rules.
COMMON_PASSWORDS = frozenset({
    "password1234", "password123", "password12", "passw0rd123", "p@ssword123", "password2024", "password2025",
    "password2026", "1q2w3e4r5t", "1q2w3e4r5t6y", "qwerty12345", "qwerty123456", "qwertyuiop1", "q1w2e3r4t5",
    "q1w2e3r4t5y6", "abc1234567", "abcd123456", "abcdef1234", "a1b2c3d4e5", "a1b2c3d4e5f6", "1234567890a",
    "123456789a", "123456789ab", "iloveyou123", "welcome123", "welcome1234", "letmein123", "admin12345",
    "administrator1", "football123", "baseball123", "dragon12345", "monkey12345", "sunshine123", "princess123",
    "trustno1234", "master12345", "shadow12345", "superman123", "michael1234", "zaq12wsxcde", "1qaz2wsx3edc",
    "zxcvbnm1234", "asdfghjkl1", "changeme123", "intellistudy1", "intellistudy123", "student1234", "student123",
    "university1", "university123", "computer123", "internet123", "summer2024", "summer2025", "winter2025",
    "spring2025", "autumn2025", "egypt123456", "cairo123456",
})


@dataclass(frozen=True, slots=True)
class PolicyResult:
    ok: bool
    reason: str = ""  # client-safe reason; never contains the password


def check_policy(password: str, settings: Settings) -> PolicyResult:
    """FR-AUTH-02 / JWT-11: length, at least one letter and one digit, not a common password."""
    if len(password) < settings.password_min_length:
        return PolicyResult(False, f"Password must be at least {settings.password_min_length} characters.")
    if len(password) > settings.password_max_length:
        return PolicyResult(False, f"Password must be at most {settings.password_max_length} characters.")
    if not re.search(r"[^\W\d_]", password):
        return PolicyResult(False, "Password must contain at least one letter.")
    if not re.search(r"\d", password):
        return PolicyResult(False, "Password must contain at least one digit.")
    if password.lower() in COMMON_PASSWORDS:
        return PolicyResult(False, "This password is too common.")
    return PolicyResult(True)


class PasswordService:
    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        # Verified against when the account does not exist, so the work done is the same (JWT-12).
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(24))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, stored_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def verify_or_dummy(self, stored_hash: str | None, password: str) -> bool:
        """Verify against ``stored_hash``, or against a dummy hash (always False) when there is none."""
        if stored_hash is None:
            self.verify(self._dummy_hash, password)
            return False
        return self.verify(stored_hash, password)

    def needs_rehash(self, stored_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(stored_hash)
        except InvalidHashError:
            return True
