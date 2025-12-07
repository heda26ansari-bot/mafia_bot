from fastapi import APIRouter, Depends, HTTPException
from ..db import database
from ..schemas import TicketCreate, TicketReply
from ..auth import get_current_admin
from ..config import settings
import httpx

router = APIRouter()

@router.get("/", dependencies=[Depends(get_current_admin)])
async def list_tickets(status: str = None):
    if status:
        return await database.fetch_all("SELECT * FROM tickets WHERE status=$1 ORDER BY created_at DESC", values=[status])
    return await database.fetch_all("SELECT * FROM tickets ORDER BY created_at DESC")

@router.post("/", status_code=201)
async def create_ticket(payload: TicketCreate):
    q = "INSERT INTO tickets (user_id, subject, message) VALUES ($1,$2,$3) RETURNING id"
    tid = await database.execute(q, values=[payload.user_id, payload.subject, payload.message])
    return {"id": tid}

@router.post("/{ticket_id}/reply", dependencies=[Depends(get_current_admin)])
async def reply_ticket(ticket_id: int, payload: TicketReply):
    # update ticket and send message to user
    await database.execute("UPDATE tickets SET admin_reply=$1, status='answered', updated_at=NOW() WHERE id=$2",
                           values=[payload.reply, ticket_id])
    user_id = await database.fetch_val("SELECT user_id FROM tickets WHERE id=$1", values=[ticket_id])
    text = f"💬 پاسخ پشتیبانی به تیکت #{ticket_id}:\n\n{payload.reply}"
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage",
                     json={"chat_id": user_id, "text": text})
    return {"ok": True}
