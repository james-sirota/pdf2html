import shutil
import tempfile
import uuid
import os
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Path as FastApiPath, Request
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse # Added FileResponse
from fastapi.staticfiles import StaticFiles 
from fastapi.templating import Jinja2Templates 
from typing import Dict, List, Any, Optional
import fitz 
import logging

from .extractor import (
    get_text_from_page,
    extract_tables_from_page,
    extract_images_from_page,
    get_image_metadata_with_paddleocr,
    extract_svg_from_page,
    PADDLEOCR_AVAILABLE,
    Ok,
    Err
)
from .html_generator import generate_page_html

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] 
)
logger = logging.getLogger(__name__) 

app = FastAPI()

module_dir = Path(__file__).parent
project_root = module_dir.parent 
app.mount("/static", StaticFiles(directory=project_root / "static"), name="static")
templates = Jinja2Templates(directory=project_root / "templates")

jobs: Dict[str, Dict[str, Any]] = {}
PDF_JOB_STORAGE_DIR = project_root / "pdf_job_storage" 
PDF_JOB_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# --- Background PDF Processing Task (condensed for brevity, assumed unchanged from previous step) ---
async def process_pdf_job(job_id: str, pdf_path_for_job: str):
    logger.info(f"Starting PDF processing for job_id: {job_id}")
    jobs[job_id]["status"] = "processing"
    doc = None
    try:
        doc = fitz.open(pdf_path_for_job)
        num_pages = doc.page_count
        jobs[job_id]["num_pages"] = num_pages
        page_results_data: Dict[int, Dict[str, Any]] = {}
        for page_num in range(num_pages):
            current_page_data: Dict[str, Any] = {
                "page_number": page_num, "text": None, "tables": [], 
                "images_metadata": [], "svg_graphics": [], "errors": []
            }
            # Text
            text_result = get_text_from_page(pdf_path_for_job, page_num)
            if isinstance(text_result, Ok): current_page_data["text"] = text_result.value
            else: current_page_data["errors"].append(f"Text extraction failed: {text_result.error}")
            # Tables
            tables_result = extract_tables_from_page(pdf_path_for_job, page_num)
            if isinstance(tables_result, Ok): current_page_data["tables"] = tables_result.value
            else: current_page_data["errors"].append(f"Table extraction failed: {tables_result.error}")
            # Images & OCR
            if PADDLEOCR_AVAILABLE:
                images_extraction_result = extract_images_from_page(pdf_path_for_job, page_num)
                if isinstance(images_extraction_result, Ok):
                    for img_info in images_extraction_result.value:
                        img_bytes = img_info.pop("image_bytes", None); item_resp = {**img_info}
                        if img_info.get("error"): pass 
                        elif img_bytes:
                            ocr_meta = get_image_metadata_with_paddleocr(img_bytes)
                            if isinstance(ocr_meta, Ok): item_resp["metadata"] = ocr_meta.value
                            else: item_resp["metadata_error"] = ocr_meta.error
                        else: item_resp["metadata_error"] = "Image bytes missing."
                        current_page_data["images_metadata"].append(item_resp)
                else: current_page_data["errors"].append(f"Image series extraction failed: {images_extraction_result.error}")
            else: current_page_data["images_metadata"].append({"metadata_note": "PaddleOCR not available."})
            # SVG
            svg_result = extract_svg_from_page(pdf_path_for_job, page_num)
            if isinstance(svg_result, Ok): current_page_data["svg_graphics"] = svg_result.value
            else: current_page_data["errors"].append(f"SVG extraction failed: {svg_result.error}")
            page_results_data[page_num] = current_page_data
        jobs[job_id]["page_data"] = page_results_data
        jobs[job_id]["status"] = "completed"
        logger.info(f"Job {job_id}: Processing completed.")
    except Exception as e:
        logger.error(f"Job {job_id}: Critical unhandled exception: {e}", exc_info=True)
        jobs[job_id]["status"] = "error"; jobs[job_id]["error_details"] = f"Job processing failed: {str(e)}"
    finally:
        if doc: doc.close()
        # Keeping job files for now as per previous step's settings
        # if os.path.exists(pdf_path_for_job):
        #     try: os.remove(pdf_path_for_job)
        #     except OSError as e_rm: logger.error(f"Job {job_id}: Error cleaning temp PDF: {e_rm}")


# --- Root Endpoint ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "message": "PDF Parser UI Initialized"})

# --- API Endpoints (Upload, Status, Page Data) ---
@app.post("/parse_pdf")
async def api_parse_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF files accepted.")
    job_id = str(uuid.uuid4())
    job_specific_dir = PDF_JOB_STORAGE_DIR / job_id
    job_specific_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize filename before saving to prevent directory traversal or other issues
    safe_filename = Path(file.filename).name # Basic sanitization
    pdf_path_for_job = job_specific_dir / safe_filename

    try:
        with open(pdf_path_for_job, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    except Exception as e: raise HTTPException(status_code=500, detail=f"Could not save PDF: {e}")
    finally:
        if hasattr(file, 'file') and hasattr(file.file, 'close'): file.file.close()
    
    jobs[job_id] = {"status": "pending", "pdf_path": str(pdf_path_for_job), 
                    "original_filename": safe_filename, "num_pages": 0, "page_data": {}, "error_details": None}
    background_tasks.add_task(process_pdf_job, job_id, str(pdf_path_for_job))
    return JSONResponse(content={"job_id": job_id, "message": "PDF parsing job initiated."})

@app.get("/status/{job_id}")
async def api_get_job_status(job_id: str = FastApiPath(..., title="Job ID")) -> JSONResponse:
    job_info = jobs.get(job_id)
    if not job_info: raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    return JSONResponse(content={"job_id": job_id, "status": job_info["status"], 
                                 "num_pages": job_info.get("num_pages",0), 
                                 "original_filename": job_info.get("original_filename"),
                                 "error_details": job_info.get("error_details") if job_info["status"] == "error" else None})

@app.get("/page/{job_id}/{page_number}/html", response_class=HTMLResponse)
async def api_get_page_html(request: Request, job_id: str = FastApiPath(..., title="Job ID"), page_number: int = FastApiPath(..., ge=0)) -> HTMLResponse:
    job_info = jobs.get(job_id)
    if not job_info: raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    if job_info["status"] in ["pending", "processing"]: raise HTTPException(status_code=202, detail=f"Job '{job_id}' still {job_info['status']}.")
    if job_info["status"] == "error": raise HTTPException(status_code=500, detail=f"Job '{job_id}' failed: {job_info.get('error_details', 'Unknown error')}")
    page_data = job_info.get("page_data", {}).get(page_number)
    if not page_data:
        max_pages = job_info.get("num_pages",0); detail = f"Page {page_number} not found for job '{job_id}'."
        if page_number >= max_pages and max_pages > 0: detail = f"Page {page_number} out of range (0-{max_pages-1}) for job '{job_id}'."
        raise HTTPException(status_code=404, detail=detail)
    
    page_data_for_html_snippet = {**page_data, "page_number": page_number}
    html_snippet = generate_page_html(page_data_for_html_snippet)
    return HTMLResponse(content=html_snippet)

@app.get("/page/{job_id}/{page_number}/raw_data")
async def api_get_page_raw_data(job_id: str = FastApiPath(..., title="Job ID"), page_number: int = FastApiPath(..., ge=0)) -> JSONResponse:
    job_info = jobs.get(job_id)
    if not job_info: raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    if job_info["status"] in ["pending", "processing"]: raise HTTPException(status_code=202, detail=f"Job '{job_id}' still {job_info['status']}.")
    if job_info["status"] == "error": raise HTTPException(status_code=500, detail=f"Job '{job_id}' failed: {job_info.get('error_details', 'Unknown error')}")
    page_data = job_info.get("page_data", {}).get(page_number)
    if not page_data:
        max_pages = job_info.get("num_pages",0); detail = f"Page {page_number} not found for job '{job_id}'."
        if page_number >= max_pages and max_pages > 0: detail = f"Page {page_number} out of range (0-{max_pages-1}) for job '{job_id}'."
        raise HTTPException(status_code=404, detail=detail)
    return JSONResponse(content={"job_id": job_id, "page_number": page_number, **page_data})

@app.get("/error/{job_id}")
async def api_get_job_error(job_id: str = FastApiPath(..., title="Job ID")) -> JSONResponse:
    job_info = jobs.get(job_id)
    if not job_info: raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    if job_info["status"] != "error":
        return JSONResponse(content={"job_id": job_id, "status": job_info["status"], "error_message": None, 
                                     "error_details_note": "Job did not fail."})
    return JSONResponse(content={"job_id": job_id, "status": "error", 
                                 "error_message": job_info.get("error_details", "Unspecified error.")})

# --- New Endpoint to Serve Job PDF ---
@app.get("/pdf_jobs/{job_id}/document.pdf")
async def api_serve_job_pdf(job_id: str = FastApiPath(..., title="Job ID")) -> FileResponse:
    logger.info(f"PDF document requested for job_id: {job_id}")
    job_info = jobs.get(job_id)
    if not job_info:
        logger.warning(f"PDF request for non-existent job_id: {job_id}")
        raise HTTPException(status_code=404, detail="Job ID not found, or PDF not available.")

    pdf_path_str = job_info.get("pdf_path")
    if not pdf_path_str:
        logger.error(f"Job {job_id} found, but 'pdf_path' is missing in job_info.")
        raise HTTPException(status_code=500, detail="PDF path not found for this job.")

    pdf_path = Path(pdf_path_str)
    if not pdf_path.exists() or not pdf_path.is_file():
        logger.error(f"PDF file missing at path '{pdf_path}' for job {job_id}, though job exists.")
        # Consider if the job should be marked as error if its PDF is gone
        raise HTTPException(status_code=404, detail="PDF file not found on server for this job. It might have been cleaned up or an error occurred.")

    # Use original filename for download if available, otherwise a generic one
    original_filename = job_info.get("original_filename", "document.pdf")
    
    logger.info(f"Serving PDF '{pdf_path}' for job {job_id} as '{original_filename}'.")
    return FileResponse(
        path=pdf_path,
        filename=original_filename, # This suggests the filename for download
        media_type='application/pdf'
    )

# Uvicorn command for manual testing (from pdf_parser_py_lib directory):
# python -m uvicorn pdf_parser.main:app --reload --port 8000 --host 0.0.0.0
