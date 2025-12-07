from databases import Database
from .config import settings

database = Database(settings.DATABASE_URL)

async def connect_db():
    await database.connect()

async def disconnect_db():
    await database.disconnect()
