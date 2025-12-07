from fastapi import APIRouter, Depends
from ..db import database
from ..auth import get_current_admin

router = APIRouter()

@router.get("/")
async def list_users(q: str = None, limit: int = 100, offset: int = 0, _=Depends(get_current_admin)):
    if q:
        return await database.fetch_all("SELECT * FROM users WHERE username ILIKE $1 OR first_name ILIKE $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3", values=[f"%{q}%", limit, offset])
    return await database.fetch_all("SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2", values=[limit, offset])

@router.get("/{user_id}")
async def get_user(user_id: int, _=Depends(get_current_admin)):
    row = await database.fetch_one("SELECT * FROM users WHERE user_id=$1", values=[user_id])
    return row
