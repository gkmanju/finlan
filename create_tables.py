#!/usr/bin/env python
"""Create (or migrate) all database tables.

Import every model so SQLAlchemy's metadata is fully populated before
calling create_all.  Running this script is idempotent — existing tables
are left untouched; only missing tables/columns are added.
"""
from app.database import Base, engine
import app.models  # noqa: F401 – registers all ORM models with Base.metadata

Base.metadata.create_all(bind=engine)

# Report which tables exist after the run
from sqlalchemy import inspect
insp = inspect(engine)
tables = sorted(insp.get_table_names())
print(f"Database tables ({len(tables)} total):")
for t in tables:
    print(f"  ✓ {t}")
print("Done.")
