from fastapi import APIRouter, HTTPException, Depends
from ..db import database
from ..schemas import AdminIn, Token, AdminOut
from ..auth import verify_password, hash_password, create_access_token
from ..config import settings

router = APIRouter()

@router.post("/login", response_model=Token)
async def login(payload: AdminIn):
    q = "SELECT id, username, password_hash, full_name FROM admins WHERE username=$1"
    row = await database.fetch_one(q, values=[payload.username])
    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    access = create_access_token({"sub": row["username"], "admin_id": row["id"]})
    return {"access_token": access}
