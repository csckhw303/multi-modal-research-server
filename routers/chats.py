from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import supabase
from auth import get_current_user

router = APIRouter(
    tags=["chats"]
)
class ChatCreate(BaseModel):
    project_id: str
    title: str
    
@router.post("/api/chats")
async def create_chat(
    chat: ChatCreate,
    clerk_id: str = Depends(get_current_user)
):
    try:
        response = supabase.table("chats").insert({
            "project_id": chat.project_id,
            "title": chat.title,
            "clerk_id": clerk_id
        }).execute()
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to create chat")
        return {
            "message": "Chat created successfully",
            "data": response.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@router.delete("/api/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    clerk_id: str = Depends(get_current_user)
):
    try:
        existing_chat = supabase.table("chats").select("*").eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if not existing_chat.data:
            raise HTTPException(status_code=404, detail="Chat not found")
        deleted_result = supabase.table("chats").delete().eq("id", chat_id).eq("clerk_id", clerk_id).execute()
        if not deleted_result.data:
            raise HTTPException(status_code=500, detail="Failed to delete chat")
        return {
            "message": "Chat deleted successfully",
            "data": deleted_result.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))