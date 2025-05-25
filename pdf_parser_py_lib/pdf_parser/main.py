import shutil
import tempfile
import uuid
import os
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Path as FastApiPath
from fastapi.responses import JSONResponse, HTMLResponse
from typing import Dict, List, Any, Optional
import fitz # PyMuPDF for getting page count
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

# --- Logging Setup ---
# Configure logging at the application level.
# This basic configuration logs to stdout. For production, consider more robust logging.
logging.basicConfig(
    level=logging.INFO, # Adjust level as needed (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()] # Log to console
)
logger = logging.getLogger(__name__) # Logger for this module
extractor_logger = logging.getLogger("pdf_parser_py_lib.pdf_parser.extractor") # Access extractor's logger if needed
# You might want to set extractor_logger.setLevel(logging.DEBUG) for more verbose logs from there.


app = FastAPI()

# --- In-memory Job Store ---
jobs: Dict[str, Dict[str, Any]] = {}
PDF_JOB_STORAGE_DIR = Path("pdf_job_storage")
PDF_JOB_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


# --- Background PDF Processing Task with Enhanced Error Handling ---
async def process_pdf_job(job_id: str, pdf_path_for_job: str):
    logger.info(f"Starting PDF processing for job_id: {job_id}")
    jobs[job_id]["status"] = "processing"
    page_results_data: Dict[int, Dict[str, Any]] = {}
    doc = None

    try:
        doc = fitz.open(pdf_path_for_job)
        num_pages = doc.page_count
        jobs[job_id]["num_pages"] = num_pages
        logger.info(f"Job {job_id}: PDF '{jobs[job_id]['original_filename']}' opened, {num_pages} pages.")

        for page_num in range(num_pages):
            logger.info(f"Job {job_id}: Processing page {page_num + 1}/{num_pages}")
            current_page_data: Dict[str, Any] = {
                "page_number": page_num,
                "text": None, "tables": [], "images_metadata": [], "svg_graphics": [],
                "errors": [] # Store errors specific to this page's processing
            }

            # 1. Extract Text
            text_result = get_text_from_page(pdf_path_for_job, page_num)
            if isinstance(text_result, Ok):
                current_page_data["text"] = text_result.value
            else:
                err_msg = f"Text extraction failed: {text_result.error}"
                logger.warning(f"Job {job_id}, Page {page_num}: {err_msg}")
                current_page_data["errors"].append(err_msg)
                current_page_data["text"] = f"Error during text extraction. Details in page errors." # Placeholder

            # 2. Extract Tables
            tables_result = extract_tables_from_page(pdf_path_for_job, page_num)
            if isinstance(tables_result, Ok):
                current_page_data["tables"] = tables_result.value
            else:
                err_msg = f"Table extraction failed: {tables_result.error}"
                logger.warning(f"Job {job_id}, Page {page_num}: {err_msg}")
                current_page_data["errors"].append(err_msg)

            # 3. Extract Images and their Metadata (PaddleOCR)
            if PADDLEOCR_AVAILABLE:
                images_extraction_result = extract_images_from_page(pdf_path_for_job, page_num)
                if isinstance(images_extraction_result, Ok):
                    extracted_images_list = images_extraction_result.value
                    for img_info in extracted_images_list:
                        img_bytes = img_info.pop("image_bytes", None)
                        current_image_response_item = {**img_info} # format, bbox, xref, error (from extraction)
                        
                        if img_info.get("error"): # Error from extract_images_from_page itself
                             logger.warning(f"Job {job_id}, Page {page_num}, ImgXref {img_info.get('xref')}: Extraction error: {img_info.get('error')}")
                             # This error is already part of current_image_response_item
                        
                        if img_bytes: # If image bytes were successfully extracted
                            metadata_ocr_result = get_image_metadata_with_paddleocr(img_bytes)
                            if isinstance(metadata_ocr_result, Ok):
                                current_image_response_item["metadata"] = metadata_ocr_result.value
                            else:
                                err_msg = f"Image OCR metadata failed (XRef {img_info.get('xref', 'N/A')}): {metadata_ocr_result.error}"
                                logger.warning(f"Job {job_id}, Page {page_num}: {err_msg}")
                                current_image_response_item["metadata_error"] = metadata_ocr_result.error # Specific to OCR step
                        elif not img_info.get("error"): # No bytes and no prior error means something unexpected
                             err_msg = f"Image OCR metadata skipped: Image bytes missing for XRef {img_info.get('xref', 'N/A')} without prior extraction error."
                             logger.warning(f"Job {job_id}, Page {page_num}: {err_msg}")
                             current_image_response_item["metadata_error"] = err_msg
                        
                        current_page_data["images_metadata"].append(current_image_response_item)
                else: # Error from extract_images_from_page (e.g. cannot open page for image list)
                    err_msg = f"Image series extraction failed: {images_extraction_result.error}"
                    logger.warning(f"Job {job_id}, Page {page_num}: {err_msg}")
                    current_page_data["errors"].append(err_msg)
            else: # PaddleOCR not available
                note_msg = "Image metadata (PaddleOCR) skipped: PaddleOCR is not available."
                current_page_data["images_metadata"].append({"metadata_note": note_msg})
                # Optionally log this once per job or less frequently if too noisy
                # logger.info(f"Job {job_id}, Page {page_num}: {note_msg}")


            # 4. Extract SVG Graphics
            svg_result = extract_svg_from_page(pdf_path_for_job, page_num)
            if isinstance(svg_result, Ok):
                current_page_data["svg_graphics"] = svg_result.value
            else:
                err_msg = f"SVG extraction failed: {svg_result.error}"
                logger.warning(f"Job {job_id}, Page {page_num}: {err_msg}")
                current_page_data["errors"].append(err_msg)
            
            page_results_data[page_num] = current_page_data
        
        jobs[job_id]["page_data"] = page_results_data
        jobs[job_id]["status"] = "completed"
        logger.info(f"Job {job_id}: Processing completed successfully.")

    except fitz.fitz.PyMuPDFError as e: # More specific PyMuPDF error for critical failures like opening PDF
        logger.error(f"Job {job_id}: Critical PyMuPDFError during processing: {e}", exc_info=True)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error_details"] = f"Job processing failed due to PDF error (possibly corrupt or encrypted): {str(e)}"
    except Exception as e:
        logger.error(f"Job {job_id}: Critical unhandled exception during processing: {e}", exc_info=True)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error_details"] = f"Job processing failed unexpectedly: {str(e)}"
    finally:
        if doc:
            doc.close()
        # Clean up the uploaded PDF file for this job after processing is finished (success or error)
        # Disabling auto-cleanup for easier debugging during development. Re-enable if desired.
        # if os.path.exists(pdf_path_for_job):
        #     try:
        #         os.remove(pdf_path_for_job)
        #         logger.info(f"Job {job_id}: Cleaned up temporary PDF '{pdf_path_for_job}'.")
        #         # Optionally remove the job-specific directory if empty, though it's good for logs/debug
        #         # if not os.listdir(Path(pdf_path_for_job).parent):
        #         #     os.rmdir(Path(pdf_path_for_job).parent)
        #     except OSError as e_rm:
        #         logger.error(f"Job {job_id}: Error cleaning up temporary PDF '{pdf_path_for_job}': {e_rm}", exc_info=True)
        pass # Keep files for now


# --- API Endpoints with Enhanced Error Handling ---

@app.post("/parse_pdf")
async def api_parse_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
) -> JSONResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        logger.warning(f"Upload attempt with invalid file: {file.filename or 'N/A'}")
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF files (.pdf extension) are accepted.")

    job_id = str(uuid.uuid4())
    logger.info(f"New job created with job_id: {job_id} for file: {file.filename}")
    
    job_specific_dir = PDF_JOB_STORAGE_DIR / job_id
    try:
        job_specific_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Could not create job directory '{job_specific_dir}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Server error: Could not create job storage directory.")

    pdf_path_for_job = job_specific_dir / (file.filename if file.filename else "uploaded.pdf")

    try:
        with open(pdf_path_for_job, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"Job {job_id}: File '{file.filename}' saved to '{pdf_path_for_job}'.")
    except Exception as e:
        logger.error(f"Job {job_id}: Could not save uploaded PDF '{pdf_path_for_job}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Server error: Could not save uploaded PDF.")
    finally:
        if hasattr(file, 'file') and hasattr(file.file, 'close'):
            file.file.close()
    
    jobs[job_id] = {
        "status": "pending", 
        "pdf_path": str(pdf_path_for_job),
        "original_filename": file.filename,
        "num_pages": 0, 
        "page_data": {},
        "error_details": None
    }

    background_tasks.add_task(process_pdf_job, job_id, str(pdf_path_for_job))
    logger.info(f"Job {job_id}: Background task scheduled.")

    return JSONResponse(
        content={"job_id": job_id, "message": "PDF parsing job initiated. Check status endpoint for updates."}
    )

@app.get("/status/{job_id}")
async def api_get_job_status(job_id: str = FastApiPath(..., title="Job ID")) -> JSONResponse:
    logger.debug(f"Status requested for job_id: {job_id}")
    job_info = jobs.get(job_id)
    if not job_info:
        logger.warning(f"Status request for non-existent job_id: {job_id}")
        raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    
    return JSONResponse(content={
        "job_id": job_id,
        "status": job_info["status"],
        "num_pages": job_info.get("num_pages", 0),
        "original_filename": job_info.get("original_filename", "N/A"),
        "error_details": job_info.get("error_details") if job_info["status"] == "error" else None
    })

@app.get("/page/{job_id}/{page_number}/html", response_class=HTMLResponse)
async def api_get_page_html(
    job_id: str = FastApiPath(..., title="Job ID"),
    page_number: int = FastApiPath(..., title="Page Number (0-indexed)", ge=0)
) -> HTMLResponse:
    logger.debug(f"HTML content requested for job_id: {job_id}, page: {page_number}")
    job_info = jobs.get(job_id)
    if not job_info:
        logger.warning(f"HTML request for non-existent job_id: {job_id}")
        raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    
    if job_info["status"] == "pending" or job_info["status"] == "processing":
        logger.info(f"HTML request for job {job_id} (page {page_number}), but job is still {job_info['status']}.")
        raise HTTPException(status_code=202, detail=f"Job '{job_id}' is still {job_info['status']}. Please try again later.")
    if job_info["status"] == "error":
        logger.warning(f"HTML request for job {job_id} (page {page_number}), but job failed: {job_info.get('error_details')}")
        raise HTTPException(status_code=500, detail=f"Job '{job_id}' failed: {job_info.get('error_details', 'Unknown error')}")
    if job_info["status"] != "completed":
        logger.error(f"Job {job_id} (page {page_number}) in unexpected state: {job_info['status']}")
        raise HTTPException(status_code=500, detail=f"Job '{job_id}' is in an unexpected state: {job_info['status']}")

    page_data = job_info.get("page_data", {}).get(page_number)
    if not page_data:
        max_pages = job_info.get("num_pages", 0)
        detail_msg = f"Page number {page_number} not found or not processed for job '{job_id}'."
        if page_number >= max_pages and max_pages > 0 :
             detail_msg = f"Page number {page_number} is out of range (0-{max_pages-1}) for job '{job_id}'."
        logger.warning(f"HTML request for job {job_id}, page {page_number}: {detail_msg}")
        raise HTTPException(status_code=404, detail=detail_msg)

    # generate_page_html expects 'page_number' key in page_data
    page_data_for_html = {**page_data, "page_number": page_number} 
    html_content = generate_page_html(page_data_for_html)
    logger.info(f"HTML content generated for job_id: {job_id}, page: {page_number}")
    return HTMLResponse(content=html_content)


@app.get("/page/{job_id}/{page_number}/raw_data")
async def api_get_page_raw_data(
    job_id: str = FastApiPath(..., title="Job ID"),
    page_number: int = FastApiPath(..., title="Page Number (0-indexed)", ge=0)
) -> JSONResponse:
    logger.debug(f"Raw data requested for job_id: {job_id}, page: {page_number}")
    job_info = jobs.get(job_id)
    if not job_info:
        logger.warning(f"Raw data request for non-existent job_id: {job_id}")
        raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")

    if job_info["status"] == "pending" or job_info["status"] == "processing":
        logger.info(f"Raw data request for job {job_id} (page {page_number}), but job is still {job_info['status']}.")
        raise HTTPException(status_code=202, detail=f"Job '{job_id}' is still {job_info['status']}. Please try again later.")
    if job_info["status"] == "error":
        logger.warning(f"Raw data request for job {job_id} (page {page_number}), but job failed: {job_info.get('error_details')}")
        raise HTTPException(status_code=500, detail=f"Job '{job_id}' failed: {job_info.get('error_details', 'Unknown error')}")
    if job_info["status"] != "completed":
        logger.error(f"Job {job_id} (page {page_number}) in unexpected state for raw data: {job_info['status']}")
        raise HTTPException(status_code=500, detail=f"Job '{job_id}' is in an unexpected state: {job_info['status']}")

    page_data = job_info.get("page_data", {}).get(page_number)
    if not page_data:
        max_pages = job_info.get("num_pages", 0)
        detail_msg = f"Page number {page_number} not found or not processed for job '{job_id}'."
        if page_number >= max_pages and max_pages > 0 :
             detail_msg = f"Page number {page_number} is out of range (0-{max_pages-1}) for job '{job_id}'."
        logger.warning(f"Raw data request for job {job_id}, page {page_number}: {detail_msg}")
        raise HTTPException(status_code=404, detail=detail_msg)
    
    logger.info(f"Raw data retrieved for job_id: {job_id}, page: {page_number}")
    # Return page_data which now includes the 'errors' list for that page.
    return JSONResponse(content={
        "job_id": job_id,
        "page_number": page_number,
        **page_data 
    })

@app.get("/error/{job_id}")
async def api_get_job_error(job_id: str = FastApiPath(..., title="Job ID")) -> JSONResponse:
    logger.debug(f"Error details requested for job_id: {job_id}")
    job_info = jobs.get(job_id)
    if not job_info:
        logger.warning(f"Error details request for non-existent job_id: {job_id}")
        raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found.")
    
    if job_info["status"] != "error":
        logger.info(f"Error details request for job {job_id}, but status is '{job_info['status']}' (not 'error').")
        return JSONResponse(content={
            "job_id": job_id,
            "status": job_info["status"],
            "error_message": None,
            "error_details_note": "Job did not fail. No error details to report."
        })
        
    logger.info(f"Error details retrieved for failed job_id: {job_id}")
    return JSONResponse(content={
        "job_id": job_id,
        "status": "error",
        "error_message": job_info.get("error_details", "An unspecified error occurred during job processing.")
    })

# --- Old Endpoints (commented out or removed) ---
# All previous direct extraction endpoints are effectively removed by this refactoring.
# If any specific old endpoint behavior is needed, it would need to be reimplemented
# on top of the new job-based system (e.g., by creating a job and waiting for a specific result).

# --- Application Startup (Example, if needed for model loading) ---
# @app.on_event("startup")
# async def startup_event():
#     # Example: Load PaddleOCR models on startup if PADDLEOCR_AVAILABLE
#     # from .extractor import get_paddle_ocr_instance # Assuming a global instance setup
#     # if PADDLEOCR_AVAILABLE:
#     #     logger.info("Initializing PaddleOCR instance on application startup...")
#     #     get_paddle_ocr_instance() # This would load models
#     #     logger.info("PaddleOCR instance initialized.")
#     pass

# To run (from pdf_parser_py_lib/): uvicorn pdf_parser.main:app --reload
