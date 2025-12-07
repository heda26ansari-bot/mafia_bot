from fastapi import APIRouter, Depends
from ..db import database
from ..auth import get_current_admin

router = APIRouter()

@router.get("/", dependencies=[Depends(get_current_admin)])
async def list_tools():
    return await database.fetch_all("SELECT * FROM tools ORDER BY id DESC")

@router.post("/", dependencies=[Depends(get_current_admin)])
async def create_tool(payload: dict):
    await database.execute("INSERT INTO tools (name, message) VALUES ($1,$2)",
                           values=[payload.get("name"), payload.get("message")])
    return {"ok": True}

@router.put("/{tool_id}", dependencies=[Depends(get_current_admin)])
async def update_tool(tool_id: int, payload: dict):
    await database.execute("UPDATE tools SET name=$1, message=$2 WHERE id=$3",
                           values=[payload.get("name"), payload.get("message"), tool_id])
    return {"ok": True}

@router.delete("/{tool_id}", dependencies=[Depends(get_current_admin)])
async def delete_tool(tool_id: int):
    await database.execute("DELETE FROM tools WHERE id=$1", values=[tool_id])
    return {"ok": True}
