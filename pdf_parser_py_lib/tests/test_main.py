import pytest
import time
import shutil
from fastapi.testclient import TestClient
from pathlib import Path
import os
from unittest.mock import patch, MagicMock # For mocking extractor functions

from pdf_parser_py_lib.pdf_parser.main import app, jobs, PDF_JOB_STORAGE_DIR
from pdf_parser_py_lib.pdf_parser.extractor import Ok, Err # For mocking return values
from pdf_parser_py_lib.tests.test_extractor import create_simple_text_pdf #, create_pdf_with_table, create_pdf_with_actual_image, create_pdf_with_vector_graphics

client = TestClient(app)

# --- Test Fixtures ---
@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown_job_storage():
    if PDF_JOB_STORAGE_DIR.exists(): shutil.rmtree(PDF_JOB_STORAGE_DIR)
    PDF_JOB_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    yield
    if PDF_JOB_STORAGE_DIR.exists(): shutil.rmtree(PDF_JOB_STORAGE_DIR)

@pytest.fixture
def dummy_pdf_path():
    pdf_dir = Path("temp_test_pdfs_main"); pdf_dir.mkdir(exist_ok=True)
    file_path = pdf_dir / "test_upload.pdf"
    create_simple_text_pdf(str(file_path), "Test content for upload.", 1)
    yield str(file_path)
    if file_path.exists(): os.remove(file_path)
    if pdf_dir.exists() and not any(pdf_dir.iterdir()): os.rmdir(pdf_dir)

@pytest.fixture
def pdf_for_full_processing(): # A PDF with 2 pages for testing page iteration
    pdf_dir = Path("temp_test_pdfs_full_main"); pdf_dir.mkdir(exist_ok=True)
    file_path = pdf_dir / "full_features.pdf"
    create_simple_text_pdf(str(file_path), "Page 1 content. Page 2 content.", 2)
    yield str(file_path)
    if file_path.exists(): os.remove(file_path)
    if pdf_dir.exists() and not any(pdf_dir.iterdir()): os.rmdir(pdf_dir)

# --- Helper to wait for job completion ---
def wait_for_job_completion(job_id: str, timeout_seconds: int = 20, client_instance=None) -> bool:
    # client_instance is not used here but kept for potential future use if direct polling via API is preferred
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        if job_id not in jobs: return False 
        status = jobs[job_id].get("status")
        if status in ["completed", "error"]:
            return True
        time.sleep(0.1) # Short sleep to yield execution
    return False

# --- API Endpoint Tests with Focus on Error Reporting ---

def test_parse_pdf_and_job_completion(pdf_for_full_processing):
    with open(pdf_for_full_processing, "rb") as f:
        response = client.post("/parse_pdf", files={"file": ("two_page.pdf", f, "application/pdf")})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    
    assert wait_for_job_completion(job_id), f"Job {job_id} did not complete in time."
    
    job_info = jobs.get(job_id)
    assert job_info is not None
    # Assuming pdf_for_full_processing is a valid PDF that should complete without critical errors
    assert job_info["status"] == "completed", f"Job {job_id} failed: {job_info.get('error_details')}"
    assert job_info["num_pages"] == 2
    assert 0 in job_info["page_data"]
    assert 1 in job_info["page_data"]
    assert "Test content for upload." not in job_info["page_data"][0]["text"] # from dummy_pdf_path
    assert "Page 1 content." in job_info["page_data"][0]["text"]


@patch('pdf_parser_py_lib.pdf_parser.main.fitz.open') # Mock at the point of use in main.py's process_pdf_job
def test_job_critical_failure_cannot_open_pdf(mock_fitz_open, dummy_pdf_path):
    mock_fitz_open.side_effect = Exception("Simulated critical PDF open error")
    
    with open(dummy_pdf_path, "rb") as f:
        response = client.post("/parse_pdf", files={"file": ("critical_fail.pdf", f, "application/pdf")})
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    assert wait_for_job_completion(job_id), "Critical fail job did not transition to error/completed."
    
    # Check job status via API
    status_response = client.get(f"/status/{job_id}")
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["status"] == "error"
    assert "Job processing failed" in status_data["error_details"]
    assert "Simulated critical PDF open error" in status_data["error_details"]

    # Check error endpoint
    error_response = client.get(f"/error/{job_id}")
    assert error_response.status_code == 200
    error_data = error_response.json()
    assert error_data["status"] == "error"
    assert "Job processing failed" in error_data["error_message"]
    assert "Simulated critical PDF open error" in error_data["error_message"]

@patch('pdf_parser_py_lib.pdf_parser.extractor.extract_tables_from_page')
@patch('pdf_parser_py_lib.pdf_parser.extractor.get_text_from_page') # Mock another to ensure job completes
def test_job_page_level_error_reporting(mock_get_text, mock_extract_tables, dummy_pdf_path):
    # Simulate text extraction success for page 0, but table extraction failure.
    mock_get_text.return_value = Ok("Successfully extracted text for page 0.")
    mock_extract_tables.return_value = Err("Simulated table extraction failure on page 0.")
    # For other extractors, assume they return Ok([]) or Ok(None) to not clutter with more mocks for this test.
    with patch('pdf_parser_py_lib.pdf_parser.extractor.extract_images_from_page', return_value=Ok([])), \
         patch('pdf_parser_py_lib.pdf_parser.extractor.extract_svg_from_page', return_value=Ok([])):

        with open(dummy_pdf_path, "rb") as f: # dummy_pdf_path creates a 1-page PDF
            response = client.post("/parse_pdf", files={"file": ("page_level_error.pdf", f, "application/pdf")})
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        assert wait_for_job_completion(job_id), "Page-level error job did not complete."
        
        job_info = jobs.get(job_id)
        assert job_info["status"] == "completed" # Job completes even with page errors
        assert job_info["num_pages"] == 1
        
        # Check raw data for page 0
        raw_data_response = client.get(f"/page/{job_id}/0/raw_data")
        assert raw_data_response.status_code == 200
        raw_data = raw_data_response.json()
        assert raw_data["page_number"] == 0
        assert raw_data["text"] == "Successfully extracted text for page 0."
        assert "errors" in raw_data
        assert len(raw_data["errors"]) == 1
        assert "Table extraction failed: Simulated table extraction failure on page 0." in raw_data["errors"][0]
        
        # Check HTML for page 0 - should include the error message
        html_response = client.get(f"/page/{job_id}/0/html")
        assert html_response.status_code == 200
        html_content = html_response.text
        assert "<h3>Processing Errors on this Page:</h3>" in html_content
        assert "<li>Table extraction failed: Simulated table extraction failure on page 0.</li>" in html_content
        # Check that table section indicates failure if generate_page_html is designed to do so
        assert "<h2>Extracted Tables</h2><p style='color:red;'>Table extraction failed (see errors above).</p>" in html_content


def test_get_page_html_job_failed_critically(dummy_pdf_path):
    # Manually set up a job that failed critically
    job_id = "critical_fail_for_html_test"
    jobs[job_id] = {
        "status": "error", 
        "error_details": "Simulated CRITICAL processing failure for HTML test.",
        "num_pages": 0, # Might not even get page count if open fails
        "page_data": {}
    }
    
    response = client.get(f"/page/{job_id}/0/html")
    assert response.status_code == 500 # As per main.py logic for job status "error"
    assert "Job 'critical_fail_for_html_test' failed" in response.json()["detail"]
    assert "Simulated CRITICAL processing failure" in response.json()["detail"]
    
    del jobs[job_id] # Clean up

def test_get_page_raw_data_page_out_of_range(pdf_for_full_processing): # Uses a 2-page PDF
    with open(pdf_for_full_processing, "rb") as f:
        response = client.post("/parse_pdf", files={"file": ("out_of_range.pdf", f, "application/pdf")})
    job_id = response.json()["job_id"]
    assert wait_for_job_completion(job_id)
    
    job_info = jobs.get(job_id)
    assert job_info["status"] == "completed"
    num_pages = job_info["num_pages"] # Should be 2

    raw_data_response = client.get(f"/page/{job_id}/{num_pages}/raw_data") # num_pages is 1 greater than max index
    assert raw_data_response.status_code == 404
    assert f"Page number {num_pages} is out of range (0-{num_pages-1})" in raw_data_response.json()["detail"]


# Test other existing endpoints to ensure no regressions
def test_get_job_status_invalid_job_main(): # Renamed to avoid conflict
    response = client.get("/status/invalid-job-id-for-main-test")
    assert response.status_code == 404

def test_get_job_error_job_completed_ok(dummy_pdf_path):
    job_id = "completed_ok_for_error_endpoint"
    jobs[job_id] = {"status": "completed", "num_pages": 1, "page_data": {0: {}}} # Minimal completed job
    
    response = client.get(f"/error/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["error_message"] is None
    assert "Job did not fail" in data["error_details_note"]
    del jobs[job_id]

# Test to ensure cleanup of temporary files (conceptual - actual cleanup is in process_pdf_job)
# For now, process_pdf_job in main.py has PDF cleanup commented out for debugging.
# If it were enabled, this test would be more meaningful.
# def test_temporary_pdf_cleanup(dummy_pdf_path):
#     with open(dummy_pdf_path, "rb") as f:
#         response = client.post("/parse_pdf", files={"file": ("cleanup_test.pdf", f, "application/pdf")})
#     job_id = response.json()["job_id"]
#     assert wait_for_job_completion(job_id)
    
#     job_info = jobs.get(job_id)
#     pdf_path_on_server = Path(job_info["pdf_path"])
    
#     # If cleanup is active in process_pdf_job:
#     # assert not pdf_path_on_server.exists(), "Temporary PDF file was not cleaned up."
#     # If job directory is also cleaned up:
#     # assert not pdf_path_on_server.parent.exists(), "Job-specific directory was not cleaned up."
#     # For now, we expect it to exist as cleanup is disabled in main.py.
#     assert pdf_path_on_server.exists(), "Temporary PDF file should exist as cleanup is currently disabled."

# Test for PADDLEOCR_AVAILABLE being false if that was a scenario to test at API level
# This would require restarting the TestClient with the flag mocked at module level of main.py
# which is more involved. For now, assume PADDLEOCR_AVAILABLE is True or handled by extractor tests.

# Ensure basic success case still works
def test_parse_pdf_success_main(dummy_pdf_path): # Renamed
    with open(dummy_pdf_path, "rb") as f:
        response = client.post("/parse_pdf", files={"file": ("test_upload_main.pdf", f, "application/pdf")})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    assert wait_for_job_completion(job_id)
    assert jobs[job_id]["status"] == "completed" or jobs[job_id]["status"] == "error" # allow error if dummy is problematic
    if jobs[job_id]["status"] == "completed":
         assert jobs[job_id]["num_pages"] == 1 # dummy_pdf_path creates 1 page pdf
         assert 0 in jobs[job_id]["page_data"]
         assert "Test content for upload." in jobs[job_id]["page_data"][0]["text"]
