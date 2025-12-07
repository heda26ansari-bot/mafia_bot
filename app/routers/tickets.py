from fastapi import APIRouter, Depends, HTTPException
from ..db import database
from ..auth import create_access_token
from ..config import settings
from pydantic import BaseModel

router = APIRouter()

class TicketCreate(BaseModel):
    user_id: int
    subject: str
    message: str

@router.get("/")
async def list_tickets(status: str = None):
    q = "SELECT * FROM tickets"
    if status:
        q += " WHERE status=$1"
        rows = await database.fetch_all(q, values=[status])
    else:
        rows = await database.fetch_all(q)
    return rows

@router.post("/", status_code=201)
async def create_ticket(payload: TicketCreate):
    q = "INSERT INTO tickets (user_id, subject, message) VALUES ($1,$2,$3) RETURNING id"
    tid = await database.execute(q, values=[payload.user_id, payload.subject, payload.message])
    return {"id": tid}

@router.post("/{ticket_id}/reply")
async def reply_ticket(ticket_id: int, payload: dict):
    # payload: {"admin_id":1, "reply":"..."}
    reply_text = payload.get("reply")
    admin_id = payload.get("admin_id")
    await database.execute("UPDATE tickets SET admin_reply=$1, status='answered', updated_at=NOW() WHERE id=$2", values=[reply_text, ticket_id])
    # send message to user via Telegram API
    # use httpx to call Telegram
    import httpx
    from ..config import settings
    user_id = await database.fetch_val("SELECT user_id FROM tickets WHERE id=$1", values=[ticket_id])
    text = f"💬 پاسخ پشتیبانی به تیکت #{ticket_id}:\n\n{reply_text}"
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", json={"chat_id": user_id, "text": text})
    return {"ok": True}
