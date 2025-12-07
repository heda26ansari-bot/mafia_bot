from fastapi import FastAPI
from .config import settings
from .db import database
from .crud import create_initial_admin_if_missing
from .routers import auth, users, tickets, tools, auto_replies, telegram

app = FastAPI(title="Cafenet Admin API")

app.include_router(auth.router, prefix="/auth")
app.include_router(users.router, prefix="/users")
app.include_router(tickets.router, prefix="/tickets")
app.include_router(tools.router, prefix="/tools")
app.include_router(auto_replies.router, prefix="/auto_replies")
app.include_router(telegram.router, prefix="/telegram")

@app.on_event("startup")
async def startup():
    await database.connect()
    # create admin if none
    await create_initial_admin_if_missing()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()
