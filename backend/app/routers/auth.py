from fastapi import APIRouter, HTTPException
from ..db import database
from ..schemas import AdminIn, TokenOut
from ..auth import verify_password, create_access_token
from ..crud import create_initial_admin_if_missing

router = APIRouter()

@router.on_event("startup")
async def _init_admin():
    # init_admin called from main instead

    pass

@router.post("/login", response_model=TokenOut)
async def login(payload: AdminIn):
    row = await database.fetch_one("SELECT id, username, password_hash FROM admins WHERE username=$1", values=[payload.username])
    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": row["username"], "admin_id": row["id"]})
    return {"access_token": token}
