from .db import database
from .auth import hash_password
from .config import settings

async def create_initial_admin_if_missing():
    q = "SELECT COUNT(*) FROM admins"
    cnt = await database.fetch_val(q)
    if cnt == 0:
        pw = settings.ADMIN_INITIAL_PASSWORD
        hashed = hash_password(pw)
        await database.execute("INSERT INTO admins (username, password_hash, full_name) VALUES ($1,$2,$3)",
                               values=[settings.ADMIN_INITIAL_USERNAME, hashed, "Initial Admin"])
        print("[init] created initial admin:", settings.ADMIN_INITIAL_USERNAME)
