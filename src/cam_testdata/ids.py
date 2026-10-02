"""Deterministic ID minting (DESIGN §5). The only place IDs come from (AGENTS.md rule 1).

Every ID is a hash of the profile seed and a stable, readable handle, so adding
a record never changes anyone else's ID and the same inputs always give the
same IDs. A registry catches collisions, including against pinned IDs.
"""

import hashlib
import re

from cam_testdata.settings import IdSettings

# Integer IDs stay inside PostgreSQL's 32-bit INTEGER.
INT_ID_MAX = 2**31 - 1


class IdError(ValueError):
    pass


class IdCollisionError(IdError):
    pass


def _digest(seed: str, handle: str) -> bytes:
    return hashlib.sha256(f"{seed}|{handle}".encode()).digest()


def encode(digest: bytes, alphabet: str, size: int) -> str:
    """Encode a digest as `size` characters of `alphabet` (base-N of the big-endian int)."""
    n = int.from_bytes(digest, "big")
    base = len(alphabet)
    chars = []
    for _ in range(size):
        n, rem = divmod(n, base)
        chars.append(alphabet[rem])
    return "".join(chars)


class IdRegistry:
    """Mints IDs for one profile and remembers which handle owns each one."""

    def __init__(self, seed: str, settings: IdSettings) -> None:
        self.seed = seed
        self.settings = settings
        self._owner: dict[str, str] = {}  # string id -> handle
        self._int_owner: dict[tuple[str, int], str] = {}  # (table, int id) -> handle
        self._local_id = re.compile(
            rf"^[a-z]{{3}}-[{re.escape(settings.alphabet)}]{{{settings.length}}}$"
        )

    # ----- string IDs --------------------------------------------------------

    def _claim(self, id_: str, handle: str) -> str:
        owner = self._owner.setdefault(id_, handle)
        if owner != handle:
            raise IdCollisionError(
                f"{id_!r} is already used by {owner!r}; can't assign it to {handle!r}"
            )
        return id_

    def _hash(self, handle: str, size: int) -> str:
        return encode(_digest(self.seed, handle), self.settings.alphabet, size)

    def mint_global(self, prefix: str, handle: str) -> str:
        if not re.fullmatch(r"[a-z]{2}", prefix):
            raise IdError(
                f"GlobalID prefix must be 2 lowercase letters, got {prefix!r}"
            )
        return self._claim(
            f"{prefix}-{self._hash(handle, self.settings.length)}", handle
        )

    def mint_local(self, prefix: str, handle: str) -> str:
        if not re.fullmatch(r"[a-z]{3}", prefix):
            raise IdError(
                f"local ID prefix must be 3 lowercase letters, got {prefix!r}"
            )
        return self._claim(
            f"{prefix}-{self._hash(handle, self.settings.length)}", handle
        )

    def mint_doi(self, handle: str) -> str:
        return self._claim(
            f"{self.settings.doi_prefix}{self._hash(handle, self.settings.doi_length)}",
            handle,
        )

    def register_explicit(
        self, id_: str, handle: str, expected_prefixes: tuple[str, ...] | None = None
    ) -> str:
        """Register a pinned GlobalID (DESIGN §5.1): it must be well formed and not collide.

        expected_prefixes: allowed 2-letter prefixes (several for any_of slots).
        """
        if not self.settings.global_id_regex().fullmatch(id_):
            raise IdError(f"{handle}: pinned ID {id_!r} isn't a valid GlobalID")
        prefix = id_.split("-", 1)[0]
        if expected_prefixes is not None and prefix not in expected_prefixes:
            raise IdError(
                f"{handle}: pinned ID {id_!r} has prefix {prefix!r}, expected one of {expected_prefixes}"
            )
        return self._claim(id_, handle)

    def is_valid_global(self, id_: str, prefix: str | None = None) -> bool:
        return bool(self.settings.global_id_regex(prefix).fullmatch(id_))

    def is_valid_local(self, id_: str) -> bool:
        return bool(self._local_id.fullmatch(id_))

    # ----- integer IDs ---------------------------------------------------------

    def mint_int(self, table: str, handle: str) -> int:
        n = int.from_bytes(_digest(self.seed, handle)[:8], "big") % INT_ID_MAX + 1
        return self._claim_int(table, n, handle)

    def register_explicit_int(self, table: str, id_: int, handle: str) -> int:
        if not 1 <= id_ <= INT_ID_MAX:
            raise IdError(f"{handle}: pinned integer ID {id_} is out of range")
        return self._claim_int(table, id_, handle)

    def _claim_int(self, table: str, id_: int, handle: str) -> int:
        owner = self._int_owner.setdefault((table, id_), handle)
        if owner != handle:
            raise IdCollisionError(
                f"{table} id {id_} is already used by {owner!r}; can't assign it to {handle!r}"
            )
        return id_

    # ----- id_map ----------------------------------------------------------------

    def owners(self) -> dict[str, str]:
        """String ID -> handle, for id_map.csv."""
        return dict(self._owner)
