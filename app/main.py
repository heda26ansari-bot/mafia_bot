import uvicorn
from fastapi import FastAPI
from .config import settings
from .db import database, connect_db, disconnect_db
from .routers import auth, tickets, tools, auto_replies, users, telegram

app = FastAPI(title="Cafenet Admin API")

@app.on_event("startup")
async def startup():
    await connect_db()

@app.on_event("shutdown")
async def shutdown():
    await disconnect_db()

# include routers
app.include_router(auth.router, prefix="/auth")
app.include_router(users.router, prefix="/users")
app.include_router(tickets.router, prefix="/tickets")
app.include_router(tools.router, prefix="/tools")
app.include_router(auto_replies.router, prefix="/auto_replies")
app.include_router(telegram.router, prefix="/telegram")
