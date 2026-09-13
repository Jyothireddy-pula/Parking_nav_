# Foundation Architecture

The API boundary is versioned under `/api/v1/`. Route handlers validate and translate HTTP concerns, services own application behavior, repositories own persistence access, and `db.py` owns the SQLAlchemy session boundary.

The frontend is one application. Public routes and protected `/admin` routes are registered together; the current guard denies admin access until authentication is implemented.

The foundation migration is intentionally empty. Future schema changes must add a new Alembic migration and preserve migration history.
