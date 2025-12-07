from fastapi import APIRouter
from ..db import database
from pydantic import BaseModel

router = APIRouter()

class AutoIn(BaseModel):
    trigger: str
    reply: str
    is_active: bool = True

@router.get("/")
async def list_auto():
    return await database.fetch_all("SELECT * FROM auto_replies ORDER BY id DESC")

@router.post("/")
async def create_auto(a: AutoIn):
    await database.execute("INSERT INTO auto_replies (trigger, reply, is_active) VALUES ($1,$2,$3)", values=[a.trigger, a.reply, a.is_active])
    return {"ok": True}
