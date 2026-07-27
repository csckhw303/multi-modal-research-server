import json
import os
import tempfile
import time

from celery import Celery
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from database import BUCKET_NAME, supabase, s3_client
from unstructured.partition.pdf import partition_pdf
from unstructured.partition.docx import partition_docx
from unstructured.partition.html import partition_html
from unstructured.partition.pptx import partition_pptx
from unstructured.partition.md import partition_md
from unstructured.partition.text import partition_text

from unstructured.chunking.title import chunk_by_title
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

llm = ChatOpenAI(model="gpt-4-turbo", temperature=0)
embedding_model = OpenAIEmbeddings(
    model=os.getenv("EMBEDDING_MODEL"),
    dimensions=1536
)
celery_app = Celery(
    'document_processor',
    broker='redis://localhost:6379/0' ,# Redis broker URL Queue  
    backend='redis://localhost:6379/0' # result go
)

def partition_document(temp_file: str, file_type: str, source_type: str = "file"):
    """Partition  document into elements based on its type.
    """
    if source_type == "url":
        return partition_html(temp_file)
    elif source_type == "pdf":
       return partition_pdf(filename=temp_file,  # Path to your PDF file
                            strategy="hi_res", # Use the most accurate (but slower) processing method of extraction
                            infer_table_structure=True, # Keep tables as structured HTML, not jumbled text
                            extract_image_block_types=["Image"], # Grab images found in the PDF
                            extract_image_block_to_payload=True # Store images as base64 data you can actually use)
                        )
    elif source_type == "docx":
       return partition_docx(filename=temp_file,
                             strategy="hi_res",
                             infer_table_structure=True)
    elif source_type == "pptx":
       return partition_pptx(filename=temp_file,
                             strategy="hi_res",
                             infer_table_structure=True)
    elif source_type == "md":
       return partition_md(filename=temp_file,
                             strategy="hi_res",
                             infer_table_structure=True)   
       
    elif source_type == "txt":
           return partition_text(filename=temp_file)

def analyze_elements(elements):
    """Analyze partitioned elements and return a summary of their categories.
    """
    text_count = 0
    table_count = 0
    image_count = 0
    title_count = 0
    other_count = 0
    
    for e in elements:
        element_name = type(e).__name__
        
        if element_name == "Table":
            table_count += 1
        elif element_name == "Image":
            image_count += 1
        elif element_name in ["Title", "Header"]:
            title_count += 1
        elif element_name in ["NarrativeText", "Text", "ListItem", "FigureCaption"]:
            text_count += 1
        else:
            other_count += 1

    return {
        "tables": table_count,
        "images": image_count,
        "text": text_count,
        "titles": title_count,
        "other": other_count,
    }

def chunk_elements(elements):
    """Chunk elements using title-based strategy and collect metrics
    """
    print(f"creating smart chunks for elements")

    chunks = chunk_by_title(elements, max_characters=3000, new_after_n_chars=2400, combine_text_under_n_chars=500)

    # collect chunking metrics
    total_chunks = len(chunks)
    chunk_metrics = {
        "total_chunks": total_chunks,
    }
    return chunks, chunk_metrics
    
def download_and_partition(document_id: str, document: dict):
    '''
    Download document from S3/ Crawl URL and partition it into elements   '''
    
    print(f"Downloading and partitioning document with ID: {document_id}")
    
    source_type = document.get("source_type")  # e.g., "pdf", "docx", "md", "txt", "url"
    if source_type == "url":
        # Implement URL download and partition logic here
        raise NotImplementedError("URL source_type is not yet supported")
    elif source_type in ("pdf", "docx", "pptx", "md", "txt"):
        s3_key = document.get("s3_key")

        fileName = document.get("filename")

        file_type = fileName.split('.')[-1] if fileName else None

        temp_file = os.path.join(tempfile.gettempdir(), f"{document_id}.{file_type}")
        print(f"Downloading file from S3 to temporary location: {temp_file}")
        s3_client.download_file(BUCKET_NAME, s3_key, temp_file)

        print(f"Partitioning document at temporary location: {temp_file}")
        try:
            elements = partition_document(temp_file, file_type, source_type=source_type)
        finally:
            os.remove(temp_file)

        return elements
    else:
        raise ValueError(f"Unsupported source_type: {source_type}")

def update_status(document_id: str, status: str, details: dict = None):
    """Update document processing status and details in the database.
    """
    result = supabase.table("project_documents").select("processing_details").eq("id", document_id).execute()
    current_details = {}
    
    if result.data and result.data[0]["processing_details"]:
        current_details = result.data[0]["processing_details"]

    if details:
        current_details.update(details) #overwrite current key or add new key-value pairs
        
    supabase.table("project_documents").update({
        "processing_status": status,
        "processing_details": current_details
    }).eq("id", document_id).execute()

def separate_content_type(chunk, source_type='file'):
    """Analyze what types of content are present in the chunk and categorize them."""
    
    is_url_source = source_type == "url"
    
    content_data = {
        "text": chunk.text,
        "tables": [],
        "images": [],
        "types": ['text']
    }
    
    if hasattr(chunk, 'metadata') and hasattr(chunk.metadata, 'orig_elements'):
        for element in chunk.metadata.orig_elements:
            element_type = type(element).__name__
            
            if element_type == "Table":
                content_data["types"].append("table")
                table_html = getattr(element.metadata, 'text_as_html', element.text)
                content_data["tables"].append(table_html)
            elif element_type == "Image" and not is_url_source:
                if hasattr(element, 'metadata') and hasattr(element.metadata, 'image_base64'):
                   content_data["types"].append("image")
                   content_data["images"].append(element.metadata.image_base64)

    content_data['types'] = list(set(content_data['types']))
    return content_data
    
def create_ai_summary(text, tables_html, images_base64):
    """Create AI-enhanced summary for mixed content"""
    
    try:
        # Build the text prompt with more efficient instructions
        prompt_text = f"""Create a searchable index for this document content.

    CONTENT:
    {text}

    """
        
        # Add tables if present
        if tables_html:
            prompt_text += "TABLES:\n"
            for i, table in enumerate(tables_html):
                prompt_text += f"Table {i+1}:\n{table}\n\n"
        
        # More concise but effective prompt
        prompt_text += """
        Generate a structured search index (aim for 250-400 words):

        QUESTIONS: List 5-7 key questions this content answers (use what/how/why/when/who variations)

        KEYWORDS: Include:
        - Specific data (numbers, dates, percentages, amounts)
        - Core concepts and themes
        - Technical terms and casual alternatives
        - Industry terminology

        VISUALS (if images present):
        - Chart/graph types and what they show
        - Trends and patterns visible
        - Key insights from visualizations

        DATA RELATIONSHIPS (if tables present):
        - Column headers and their meaning
        - Key metrics and relationships
        - Notable values or patterns

        Focus on terms users would actually search for. Be specific and comprehensive.

        SEARCH INDEX:"""
        
        # Build message content starting with the text prompt
        message_content = [{"type": "text", "text": prompt_text}]
        
        # Add images to the message
        for i, image_base64 in enumerate(images_base64):
            message_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
            })
            print(f"🖼️ Image {i+1} included in summary request")
        
        message = HumanMessage(content=message_content)
        

        response = llm.invoke([message])
        
        return response.content
        
    except Exception as e:
        print(f" AI summary failed: {e}")    

def get_page_number(chunk, chunk_index):
    """Get page number from chunk or use fallback"""
    if hasattr(chunk, 'metadata'):
        page_number = getattr(chunk.metadata, 'page_number', None)
        if page_number is not None:
            return page_number
    
    # Fallback: use chunk index as page number
    return chunk_index + 1    
      
def summarise_chunks(chunks, document_id, source_type='file'):
    """Transform chunks into searchable content with AI summarization."""
    
    langchain_documents = []
    total_chunks = len(chunks)
    
    for i, chunk in enumerate(chunks):
        current_chunk = i+1
        update_status(document_id, 'summarising', {"summarising": {"current_chunk": current_chunk, "total_chunks": total_chunks}})
        content_data = separate_content_type(chunk, source_type=source_type)
        
        print(f" Types found: {content_data['types']}")
        print(f" Tables: {len(content_data['tables'])}, Images: {len(content_data['images'])}")

        if content_data['tables'] or content_data['images']:
            print(f"   -> Creating AI summary for mixed content")
            
            try:
                enhanced_content = create_ai_summary(
                    content_data['text'],
                    content_data['tables'],
                    content_data['images']
                )
                print(f"    ->AI summary created successfully")
                print(f"    ->Enhanced content preview: {enhanced_content[:200]}")
            except Exception as e:
                print(f"    ->Failed to create AI summary: {e}")
                enhanced_content = content_data['text']

        else:
            enhanced_content = content_data['text']
            
        # Build the original_content structure
        original_content = {'text': content_data['text']}
        if content_data['tables']:
            original_content['tables'] = content_data['tables']
        if content_data['images']:
            original_content['images'] = content_data['images']    

        # Create langChain Document 
        processed_chunk = {
                    'content': enhanced_content,
                    'original_content': original_content, 
                    'type': content_data['types'],
                    'page_number': get_page_number(chunk, i),
                    'char_count': len(enhanced_content)
                }
        langchain_documents.append(processed_chunk)
    
    print(f"✅ Processed {len(langchain_documents)} chunks")
    return langchain_documents

def store_chunks_with_embeddings(document_id, processed_chunks):
    """Generated embeddings for the given chunks and store them in the database."""
    if not processed_chunks:
        print("No chunks to process")
        return[]
    
    print(f"Generating embeddings for {len(processed_chunks)} chunks")
    
    texts = [chunk["content"] for chunk in processed_chunks]
    
    batch_size = 10
    all_embeddings = []
    # Generate embeddings in batches to avoid overwhelming the embedding service
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+batch_size]
        batch_embeddings = embedding_model.embed_documents(batch_texts)  # Assuming you have a function to generate embeddings
        all_embeddings.extend(batch_embeddings)
    
    
    # Store embeddings in the database
    print(f"Store chunks with embeddings in database")
    stored_chunk_ids = []
    
    for i , (chunk_data, embedding) in enumerate(zip(processed_chunks, all_embeddings)):
        
        chunk_data_with_embedding = {
            **chunk_data,
            "embedding": embedding,
            "document_id": document_id,
            "chunk_index": i
        }
        
        result = supabase.table("document_chunks").insert(chunk_data_with_embedding).execute()
        stored_chunk_ids.append(result.data[0]["id"])
    
    print(f"Successfully stored {len(processed_chunks)} chunks with embeddings")
    return stored_chunk_ids
    
@celery_app.task
def process_document(document_id: str):
    """Real document processing
    """
    try:
        supabase.table("project_documents").update({"processing_status": "processing"}).eq("id", document_id).execute()

        doc_result = supabase.table("project_documents").select("*").eq("id", document_id).execute()
        document = doc_result.data[0] if doc_result.data else None
        source_type = document.get('source_type', 'file')
        
        # 1  download file and partition
        update_status(document_id, "partitioning")
        elements = download_and_partition(document_id, document)
                
        element_summary = analyze_elements(elements)
        print(f"Document with ID: {document_id} has {element_summary['tables']} tables, {element_summary['images']} images, {element_summary['text']} text elements, {element_summary['titles']} titles, and {element_summary['other']} other elements.")
        update_status(document_id, "chunking", {"partitioning": {"elements_found": element_summary}})

        # 2 chunk elements
        chunks, chunk_metrics = chunk_elements(elements)  # Assuming you have a function to chunk the elements
        print(f"Document with ID: {document_id} has been chunked into {chunk_metrics['total_chunks']} chunks.")
        update_status(document_id, "summarising", {"chunking": chunk_metrics})
        
        # 3 summarise chunks
        summarised_chunks = summarise_chunks(chunks, document_id, source_type)
        print(f"Document with ID: {document_id} has been summarised into {len(summarised_chunks)} chunks.")
        update_status(document_id, "vectorization")
        
        # 4 Vectorize and store
        stored_chunk_ids = store_chunks_with_embeddings(document_id, summarised_chunks)
        print(f"Document with ID: {document_id} has been stored with {len(stored_chunk_ids)} chunks.")
        update_status(document_id, "completed")
        
        print(f"☑ Celery task completed for document with ID: {document_id}")
        
    except Exception as e:
        print(f"Error processing document with ID: {document_id}: {e}")
        update_status(document_id, "failed", {"error": str(e)})