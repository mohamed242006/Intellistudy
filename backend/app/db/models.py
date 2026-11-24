"""ORM models. Importing this module registers every table on ``Base.metadata`` (used by Alembic).

M0 defines none; M1 adds ``User``, ``RefreshToken`` and ``Course``. Every model holding user data must follow contract
OWN-01 (a non-nullable path to ``users.id``; ``owner_id`` on directly addressed tables) and use the portable types in
``backend.app.db.base``.
"""

from backend.app.db.base import Base

__all__ = ["Base"]
