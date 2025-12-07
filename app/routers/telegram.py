from fastapi import APIRouter, HTTPException
from ..config import settings
import httpx

router = APIRouter()

@router.post("/send_message")
async def send_message(payload: dict):
    # payload: {"chat_id": 123, "text":"..."}
    chat_id = payload.get("chat_id")
    text = payload.get("text")
    if not chat_id or not text:
        raise HTTPException(400, "chat_id and text required")
    async with httpx.AsyncClient() as client:
        r = await client.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})
        return {"status": r.status_code, "body": r.json()}
