import uuid

from fastapi import APIRouter, Depends, File, HTTPException
from pydantic import BaseModel
from database import supabase, s3_client, BUCKET_NAME
from auth import get_current_user
from tasks import process_document
router = APIRouter(
    tags=["files"]
)
class UrlAddRequest(BaseModel):
    url: str
class FileUploadRequest(BaseModel):
    filename: str
    file_size: int
    file_type: str
    
@router.get("/api/projects/{project_id}/files")
async def get_project_files(project_id: str, clerk_id: str = Depends(get_current_user)):
    try:
        response = supabase.table("project_documents").select("*").eq("project_id", project_id).eq("clerk_id", clerk_id).order("created_at",desc=True).execute()

        return {
            "message": "Project files retrieved successfully",
            "data": response.data or []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/projects/{project_id}/files/upload-url")
async def get_upload_url (project_id: str,
                          file_request: FileUploadRequest,
                          clerk_id: str = Depends(get_current_user)):
    try:
        project =supabase.table("projects").select("*").eq("id", project_id).execute()
        if not project.data:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # s3 key for the file
        file_extension = file_request.filename.split(".")[-1] if '.' in file_request.filename else ''
        unique_id = str(uuid.uuid4())
        s3_key = f"projects/{project_id}/documents/{unique_id}.{file_extension}"
        
        # presigned url (it is kind of permission to upload the file to S3)
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
             Params={
                 "Bucket": BUCKET_NAME,
                 "Key": s3_key,
                 "ContentType": file_request.file_type
             },
             ExpiresIn=3600
        )
        print(f"File: {file_request.filename}, Type: {file_request.file_type}")
        project_document_inserted = supabase.table("project_documents").insert({
            "project_id": project_id,
            "filename": file_request.filename,
            "file_size": file_request.file_size,
            "file_type": file_request.file_type,
            "s3_key": s3_key,
            "processing_status": "uploading",
            "clerk_id": clerk_id,
            "source_type": file_extension.lower()
        }).execute()
        
        if not project_document_inserted.data:
            raise HTTPException(status_code=500, detail="Failed to insert project document record")
        
        
        return {
            "message": "Presigned URL generated successfully",
            "data": {
                "upload_url": presigned_url,
                "s3_key": s3_key,
                "document": project_document_inserted.data[0]
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 
    
    
@router.post("/api/projects/{project_id}/files/confirm-upload")
async def get_confirm_file_upload (project_id: str,
                          confirm_request: dict,
                          clerk_id: str = Depends(get_current_user)):  
    
    try:
        s3_key = confirm_request.get("s3_key")
        if not s3_key:
            raise HTTPException(status_code=400, detail="s3_key is required")
        
        result = supabase.table("project_documents").update({"processing_status": "queued"}) \
        .eq("project_id", project_id) \
        .eq("s3_key", s3_key) \
        .eq("clerk_id", clerk_id) \
        .execute()
        
        if not result.data:
            raise HTTPException(status_code=404, detail="Document not found")
        
        document = result.data[0]
        document_id = document['id']
        # {"task": "process_document", "id": document_id, "args": [file_path]} will be create by triggering
        # the task into redis
        task = process_document.delay(document_id)
        # save this task_id into project_documents table
        updated_document = supabase.table("project_documents").update({"task_id": task.id}).eq("id",document_id).execute()
        return {
            "message": "Upload confirmed, processing started with Celery",
            "data": result.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 

@router.delete("/api/projects/{project_id}/files/{file_id}")
async def delete_project_file(
    project_id: str,
    file_id: str,
    clerk_id: str = Depends(get_current_user)
):
    try:
        existing_document = supabase.table("project_documents").select("*") \
            .eq("id", file_id) \
            .eq("project_id", project_id) \
            .eq("clerk_id", clerk_id) \
            .execute()
        if not existing_document.data:
            raise HTTPException(status_code=404, detail="Document not found")

        document = existing_document.data[0]
        s3_key = document.get("s3_key")
        if s3_key:
            s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)

        deleted_result = supabase.table("project_documents").delete() \
            .eq("id", file_id) \
            .eq("project_id", project_id) \
            .eq("clerk_id", clerk_id) \
            .execute()
        if not deleted_result.data:
            raise HTTPException(status_code=500, detail="Failed to delete document")

        return {
            "message": "Document deleted successfully",
            "data": deleted_result.data[0]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/projects/{project_id}/files/{file_id}/chunks")
async def get_document_chunks(
    project_id: str,
    file_id: str,
    clerk_id: str = Depends(get_current_user)
):
    try:
        project_result = supabase.table('projects').select('id').eq('id', project_id).eq('clerk_id', clerk_id).execute()
        
        if not project_result.data:
            raise HTTPException(status_code=404, detail="Project not found or access denied")
        
        doc_result = supabase.table('project_documents').select('id').eq('id', file_id).eq('project_id', project_id).execute()
        
        if not doc_result.data:
            raise HTTPException(status_code=404, detail="Document not found")
        
        chunks_result = supabase.table('document_chunks').select('*').eq('document_id', file_id).order('chunk_index').execute()
        
        return {
            "message": "Document chunks retrieved successfully",
            "data": chunks_result.data or []
        }

    except Exception as e:
        print(f"ERROR getting chunks: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get document chunks: {str(e)}")

                
        
@router.post("/api/projects/{project_id}/urls")
async def add_website_url(project_id: str, url_request: UrlAddRequest, clerk_id: str = Depends(get_current_user)):
    try:
        url = url_request.url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url
        
        result = supabase.table("project_documents").insert({
            "project_id": project_id,
            "processing_status": "queued",
            "filename": "",
            "clerk_id": clerk_id,
            "file_size": 0,
            "file_type": "text/html",
            "source_type": "url",
            "source_url": url,
            "s3_key": ""
                
        }).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to insert URL record")

        #baground processing can be triggered here, e.g., sending a task to Celery
        document = result.data[0]
        document_id = document['id']
        # {"task": "process_document", "id": document_id, "args": [file_path]} will be create by triggering
        # the task
        task = process_document.delay(document_id)
        # save this task_id into project_documents table
        updated_document = supabase.table("project_documents").update({"task_id": task.id}).eq("id",document_id).execute()
             
        return {
            "message": "Website URL added successfully",
            "data": result.data[0]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 