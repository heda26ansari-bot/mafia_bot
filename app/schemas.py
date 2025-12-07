from pydantic import BaseModel
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class AdminIn(BaseModel):
    username: str
    password: str

class AdminOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str]
