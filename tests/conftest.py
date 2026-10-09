"""Tests use a throwaway SQLite file instead of the real PostgreSQL database.
This must run before `app.db` is imported, which is why it lives in conftest.py."""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")
