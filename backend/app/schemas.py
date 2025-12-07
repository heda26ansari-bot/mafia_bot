from pydantic import BaseModel
from typing import Optional

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class AdminIn(BaseModel):
    username: str
    password: str

class AdminOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str]

class TicketCreate(BaseModel):
    user_id: int
    subject: str
    message: str

class TicketReply(BaseModel):
    admin_id: int
    reply: str

class AutoReplyIn(BaseModel):
    trigger: str
    reply: str
    is_active: bool = True
