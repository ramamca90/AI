"""Argon2id password hashing, run off the event loop.

Hashing is deliberately slow (CPU + memory hard); doing it inline would
block every other request on this worker, so it runs in a thread.
"""

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

# Verified against when the user does not exist so response time does not
# reveal which emails are registered (user-enumeration via timing).
_DUMMY_HASH = _hasher.hash("orderflow-timing-equaliser")


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            return False

    ok = await asyncio.to_thread(_verify)
    return ok and password_hash is not None
