from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from database import supabase
from auth import get_current_user

router = APIRouter(
    tags=["chats"]
)

llm = ChatOpenAI(model="gpt-4o", temperature=0)
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
    
@router.get("/api/chats/{chat_id}")
async def get_chat(
    chat_id: str,
    clerk_id: str = Depends(get_current_user)
):
    try:
        # Get the chat and verify it belongs to the user AND has a project_id
        result = supabase.table('chats').select('*').eq('id', chat_id).eq('clerk_id', clerk_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Chat not found or access denied")
        
        chat = result.data[0]
        
        # Get messages for this chat
        messages_result = supabase.table('messages').select('*').eq('chat_id', chat_id).order('created_at', desc=False).execute()
        
        # Add messages to chat object
        chat['messages'] = messages_result.data or []
        
        return {
            "message": "Chat retrieved successfully",
            "data": chat
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chat: {str(e)}")

class SendMessageRequest(BaseModel):
    content: str


@router.post("/api/projects/{project_id}/chats/{chat_id}/messages")
async def send_message(
    chat_id: str,
    request: SendMessageRequest,
    clerk_id: str = Depends(get_current_user)
):
    """
        User message → LLM → AI response
    """
    try:
        message = request.content
        
        print(f"💬 New message: {message[:50]}...")
        
        # 1. Save user message
        print(f"💾 Saving user message...")
        user_message_result = supabase.table('messages').insert({
            "chat_id": chat_id,
            "content": message,
            "role": "user",
            "clerk_id": clerk_id
        }).execute()
        
        user_message = user_message_result.data[0]
        print(f"✅ User message saved: {user_message['id']}")
        
        # 2. Call LLM with system prompt + user message
        print(f"🤖 Calling LLM...")
        messages = [
            SystemMessage(content="You are a helpful AI assistant. Provide clear, concise, and accurate responses."),
            HumanMessage(content=message)
        ]
        
        response = llm.invoke(messages)
        ai_response = response.content
        
        print(f"✅ LLM response received: {len(ai_response)} chars")
        
        # 3. Save AI message
        print(f"💾 Saving AI message...")
        ai_message_result = supabase.table('messages').insert({
            "chat_id": chat_id,
            "content": ai_response,
            "role": "assistant",
            "clerk_id": clerk_id,
            "citations": []
        }).execute()
        
        ai_message = ai_message_result.data[0]
        print(f"✅ AI message saved: {ai_message['id']}")
        
        # 4. Return data
        return {
            "message": "Messages sent successfully",
            "data": {
                "userMessage": user_message,
                "aiMessage": ai_message
            }
        }
        
    except Exception as e:
        print(f"❌ Error in send_message: {str(e)}")
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