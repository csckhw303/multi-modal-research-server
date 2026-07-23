from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import supabase
from auth import get_current_user
router = APIRouter(
    tags=["projects"]
)

class ProjectCreate(BaseModel):
    name: str
    description: str


@router.post("/api/projects")
async def create_project(project: ProjectCreate, clerk_id: str = Depends(get_current_user)):
    try:
        project_result = supabase.table("projects").insert({
            "name": project.name,
            "description": project.description,
            "clerk_id": clerk_id
        }).execute()
        
        if not project_result.data:
            raise HTTPException(status_code=500, detail="Failed to create project")
        
        # project setting
        created_project = project_result.data[0]
        project_id = created_project["id"]
        setting_result = supabase.table("project_settings").insert({
            "project_id": project_id,
             "embedding_model": "text-embedding-3-large",
             "rag_strategy": "basic",
             "agent_type": "agentic",
             "chunks_per_search": 5,
             "final_context_size": 10,
             "similarity_threshold": 0.3,
             "number_of_queries": 5,
             "reranking_enabled": True,
             "reranking_model": "rerank-english-v3.0",
             "vector_weight": 0.7,
             "keyword_weight": 0.3
        }).execute()
        
        if not setting_result.data:
            # need to clean up project
            supabase.table("projects").delete().eq("id", project_id).execute()
            raise HTTPException(status_code=500, detail="Failed to create project setting")
        
        return {
            "message": "Project created successfully",
            "data": created_project
        }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str, clerk_id: str = Depends(get_current_user)):
    try:
        existing_project = supabase.table("projects").select("*").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not existing_project.data:
            raise HTTPException(status_code=404, detail="project not found")
        # cascade delete all related data
        deleted_result = supabase.table("projects").delete().eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not deleted_result.data:
            raise HTTPException(status_code=500, detail="Failed to delete project")
        
        return {
            "message": "Deleted project successfully",
            "data": deleted_result.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
       
@router.get("/api/projects")
async def get_projects(clerk_id: str = Depends(get_current_user)):
    try:
        response = supabase.table("projects").select("*").eq("clerk_id", clerk_id).execute()
        return {
            "message": "Projects retrieved successfully",
            "data": response.data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/api/projects/{project_id}")
async def get_project(project_id: str, clerk_id: str = Depends(get_current_user)):
    try:
        response = supabase.table("projects").select("*").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Project not found")
        return {
            "message": "Project retrieved successfully",
            "data": response.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@router.get("/api/projects/{project_id}/chats")
async def get_project_chats(project_id: str, clerk_id: str = Depends(get_current_user)):
    try:
        response = supabase.table("chats").select("*").eq("project_id", project_id).eq("clerk_id", clerk_id).order("created_at",desc=True).execute()
       
        return {
            "message": "Chats retrieved successfully",
            "data": response.data or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@router.get("/api/projects/{project_id}/settings")
async def get_project_settings(project_id: str, clerk_id: str = Depends(get_current_user)):
    try:
        # project = supabase.table("projects").select("id").eq("id", project_id).eq("clerk_id", clerk_id).execute()
        # if not project.data:
        #     raise HTTPException(status_code=404, detail="Project not found")

        response = supabase.table("project_settings").select("*").eq("project_id", project_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Project settings not found")
        return {
            "message": "Project settings retrieved successfully",
            "data": response.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))