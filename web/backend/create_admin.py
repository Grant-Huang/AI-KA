"""Run once to create the initial admin/test user: python -m backend.create_admin"""
import hashlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from aika import db as dbm
from aika.paths import db_path
from backend.repo_paths import repository_root

conn = dbm.open_db(db_path(repository_root()))
dbm.ensure_schema(conn)

username = "admin"
display_name = "管理员"
password = "admin123"
pw_hash = hashlib.sha256(password.encode()).hexdigest()

try:
    user = dbm.create_user(conn, username=username, display_name=display_name, password_hash=pw_hash)
    print(f"Created user: {user.username} (id={user.id})")
except Exception as e:
    print(f"User may already exist: {e}")
