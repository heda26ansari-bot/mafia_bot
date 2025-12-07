from fastapi import APIRouter, Depends
from ..db import database
from ..schemas import AutoReplyIn
from ..auth import get_current_admin

router = APIRouter()

@router.get("/", dependencies=[Depends(get_current_admin)])
async def list_auto():
    return await database.fetch_all("SELECT * FROM auto_replies ORDER BY id DESC")

@router.post("/", dependencies=[Depends(get_current_admin)])
async def create_auto(a: AutoReplyIn):
    await database.execute("INSERT INTO auto_replies (trigger, reply, is_active) VALUES ($1,$2,$3)",
                           values=[a.trigger, a.reply, a.is_active])
    return {"ok": True}
