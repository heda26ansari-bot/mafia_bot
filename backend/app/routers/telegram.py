from fastapi import APIRouter, HTTPException, Depends
from ..config import settings
import httpx
from ..auth import get_current_admin

router = APIRouter()

@router.post("/send_message", dependencies=[Depends(get_current_admin)])
async def send_message(payload: dict):
    chat_id = payload.get("chat_id")
    text = payload.get("text")
    if not chat_id or not text:
        raise HTTPException(status_code=400, detail="chat_id and text required")
    async with httpx.AsyncClient() as c:
        resp = await c.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})
    return {"status": resp.status_code, "body": await resp.json()}
