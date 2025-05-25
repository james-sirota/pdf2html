import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock, PropertyMock
import pandas as pd 
import numpy as np
import io 
import fitz # For fitz.fitz.PyMuPDFError
from PIL import UnidentifiedImageError # For testing image errors

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors

from pdf_parser_py_lib.pdf_parser.extractor import (
    extract_text_from_pdf_page_direct,
    extract_text_with_ocr, 
    determine_page_extraction_strategy,
    get_text_from_page,
    is_page_primarily_text, # Kept, ensure its error handling is also reviewed if used
    extract_tables_from_page,
    extract_images_from_page,      
    get_image_metadata_with_paddleocr, 
    extract_svg_from_page, 
    PADDLEOCR_AVAILABLE,          
    Ok,
    Err
)
# Ensure pytesseract specific errors can be imported if needed for mocking
try:
    from pytesseract import TesseractNotFoundError, TesseractError
except ImportError:
    class TesseractNotFoundError(Exception): pass # Define dummy if not installed
    class TesseractError(Exception): pass       # Define dummy if not installed


# --- Helper to create a minimal PNG for embedding ---
def create_minimal_png_bytes(size=(60,30), text="Test") -> bytes:
    img = Image.new("RGB", size, color="red"); draw = ImageDraw.Draw(img)
    draw.text((5, 5), text, fill="white"); byte_io = io.BytesIO()
    img.save(byte_io, format="PNG"); return byte_io.getvalue()

# --- PDF Creation Helpers (condensed) ---
def create_simple_text_pdf(file_path: str, text_content: str, num_pages: int = 1):
    c = canvas.Canvas(file_path, pagesize=letter)
    for i in range(num_pages): c.drawString(1*inch, 7*inch, f"Page {i+1}: {text_content}"); c.showPage()
    c.save()

def create_pdf_with_actual_image(file_path: str, num_pages: int = 1):
    c = canvas.Canvas(file_path, pagesize=letter); png_bytes = create_minimal_png_bytes()
    from reportlab.lib.utils import ImageReader; img_reader = ImageReader(io.BytesIO(png_bytes))
    for i in range(num_pages):
        c.drawString(1*inch, 7*inch, f"Page {i+1} with image.")
        c.drawImage(img_reader, 1*inch, 5*inch, width=1.5*inch, height=0.75*inch); c.showPage()
    c.save()

def create_pdf_with_table(file_path: str, num_pages: int = 1):
    c = canvas.Canvas(file_path, pagesize=letter)
    for i in range(num_pages):
        data = [["H1", "H2"], ["R1C1", "R1C2"]]; table = Table(data, colWidths=[1.5*inch]*2)
        table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black)]))
        table.wrapOn(c, 7*inch, 5*inch); table.drawOn(c, 1*inch, 5*inch); c.showPage()
    c.save()

def create_pdf_with_vector_graphics(file_path: str, num_pages: int = 1, has_graphics: bool = True):
    c = canvas.Canvas(file_path, pagesize=letter)
    for i in range(num_pages):
        if has_graphics: c.line(1*inch, 7*inch, 3*inch, 7*inch)
        c.showPage()
    c.save()

# --- Pytest Fixtures (condensed) ---
@pytest.fixture
def text_pdf():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: path = tmp.name
    create_simple_text_pdf(path, "Direct text.", 1); yield path; os.remove(path)

@pytest.fixture
def pdf_with_embedded_image():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: path = tmp.name
    create_pdf_with_actual_image(path, 1); yield path; os.remove(path)

@pytest.fixture
def pdf_with_a_table():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: path = tmp.name
    create_pdf_with_table(path, 1); yield path; os.remove(path)
    
@pytest.fixture
def pdf_with_vectors():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: path = tmp.name
    create_pdf_with_vector_graphics(path, 1, True); yield path; os.remove(path)

@pytest.fixture
def pdf_without_vectors():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: path = tmp.name
    create_pdf_with_vector_graphics(path, 1, False); yield path; os.remove(path)
    
@pytest.fixture
def empty_content_pdf(): 
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: path = tmp.name
    c = canvas.Canvas(path, letter); c.showPage(); c.save(); yield path; os.remove(path)
    
@pytest.fixture
def non_pdf_file(): # Actually a text file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp: tmp.write(b"text"); path = tmp.name
    yield path; os.remove(path)

# --- Mock Classes (condensed) ---
class MockPaddleOCR:
    def __init__(self, **kwargs): self.kwargs = kwargs
    def ocr(self, img_path_or_np_array, cls=True):
        if hasattr(img_path_or_np_array, 'shape') and img_path_or_np_array.shape == (30,60,3):
             return [[[[[10.,10.],[50.,10.],[50.,20.],[10.,20.]], ('Mocked Text',0.95)]]]
        return [[]] # Simulate no text detected or an empty result

class MockTable:
    def __init__(self, data): self.df = pd.DataFrame(data)
class MockTableList:
    def __init__(self, tables_data=None): self._tables = [MockTable(data if data else [[]]) for data in (tables_data or [])]; self.n = len(self._tables)
    def __getitem__(self, index): return self._tables[index]
    def __iter__(self): return iter(self._tables)


# --- Tests for Extractor Functions focusing on Error Handling ---

# extract_text_from_pdf_page_direct
@patch('fitz.open')
def test_direct_text_open_pdf_error(mock_fitz_open, text_pdf):
    mock_fitz_open.side_effect = fitz.fitz.PyMuPDFError("Simulated PDF corruption")
    result = extract_text_from_pdf_page_direct(text_pdf, 0)
    assert isinstance(result, Err)
    assert "Failed to open PDF (direct text extraction): Possible corruption or encryption." in result.error
    assert "Simulated PDF corruption" in result.error

@patch('fitz.Document.load_page')
def test_direct_text_load_page_runtime_error(mock_load_page, text_pdf):
    # Need to mock fitz.open to return a mock document that has this mock_load_page
    mock_doc = MagicMock()
    mock_doc.page_count = 1
    mock_doc.load_page.side_effect = RuntimeError("Simulated page loading error")
    
    with patch('fitz.open', return_value=mock_doc):
        result = extract_text_from_pdf_page_direct(text_pdf, 0)
        assert isinstance(result, Err)
        assert "Failed to extract direct text from page 0: PyMuPDF runtime error." in result.error
        assert "Simulated page loading error" in result.error

# extract_text_with_ocr (Tesseract)
@patch('pdf_parser_py_lib.pdf_parser.extractor.pytesseract.image_to_string')
def test_tesseract_ocr_tesseract_error(mock_image_to_string, pdf_with_embedded_image):
    mock_image_to_string.side_effect = TesseractError("Simulated Tesseract processing error")
    result = extract_text_with_ocr(pdf_with_embedded_image, 0)
    assert isinstance(result, Err)
    assert "Tesseract OCR processing failed for page 0" in result.error
    assert "Simulated Tesseract processing error" in result.error

@patch('pdf_parser_py_lib.pdf_parser.extractor.pytesseract.image_to_string')
def test_tesseract_ocr_not_found_error(mock_image_to_string, pdf_with_embedded_image):
    mock_image_to_string.side_effect = TesseractNotFoundError
    result = extract_text_with_ocr(pdf_with_embedded_image, 0)
    assert isinstance(result, Err)
    assert "Tesseract command not found or not configured correctly" in result.error

# extract_tables_from_page (Camelot)
@patch('pdf_parser_py_lib.pdf_parser.extractor.camelot.read_pdf')
def test_extract_tables_ghostscript_error_simulated(mock_read_pdf, pdf_with_a_table):
    mock_read_pdf.side_effect = Exception("gs not found or some ghostscript specific error")
    result = extract_tables_from_page(pdf_with_a_table, 0)
    assert isinstance(result, Err)
    assert "Table extraction failed: Ghostscript error." in result.error
    assert "gs not found" in result.error # Check if original error detail is included

@patch('pdf_parser_py_lib.pdf_parser.extractor.camelot.read_pdf')
def test_extract_tables_opencv_error_simulated(mock_read_pdf, pdf_with_a_table):
    # Simulate an error message that implies OpenCV issues
    mock_read_pdf.side_effect = Exception("module 'cv2' has no attribute 'some_function' or other opencv specific message")
    result = extract_tables_from_page(pdf_with_a_table, 0)
    assert isinstance(result, Err)
    assert "Table extraction failed: OpenCV error." in result.error
    assert "cv2" in result.error


# extract_images_from_page
@patch('fitz.Document.extract_image')
def test_extract_images_extraction_failure_for_one_image(mock_extract_image, pdf_with_embedded_image):
    # Simulate PyMuPDF failing to extract one specific image xref
    # This requires pdf_with_embedded_image to actually have an image that get_images finds.
    # We then mock the subsequent extract_image call.
    
    # Let's assume get_images returns one image with xref 123
    mock_page_instance = MagicMock()
    mock_page_instance.get_images.return_value = [(123, 0, 100, 100, 8, "DeviceRGB", "", "img0", 0)] # Simplified tuple
    mock_page_instance.get_drawings.return_value = [{"type":"image", "xref":123, "rect": fitz.Rect(0,0,100,100)}]

    mock_doc_instance = MagicMock()
    mock_doc_instance.page_count = 1
    mock_doc_instance.load_page.return_value = mock_page_instance
    # First call to extract_image succeeds, second fails for a different xref (if any)
    # Or, more simply, make it fail for the first one found.
    mock_extract_image.side_effect = Exception("Simulated image data corruption for xref 123")

    with patch('fitz.open', return_value=mock_doc_instance):
        result = extract_images_from_page(pdf_with_embedded_image, 0)
        assert isinstance(result, Ok)
        images = result.value
        assert len(images) == 1
        img_info = images[0]
        assert img_info["xref"] == 123
        assert img_info["image_bytes"] is None
        assert "error" in img_info
        assert "Failed to extract image bytes for xref 123" in img_info["error"]
        assert "Simulated image data corruption" in img_info["error"]

# get_image_metadata_with_paddleocr
@patch('pdf_parser_py_lib.pdf_parser.extractor.PADDLEOCR_AVAILABLE', True)
@patch('pdf_parser_py_lib.pdf_parser.extractor.PaddleOCR') # Patch the class
def test_paddleocr_init_failure(MockPaddleOCRClass, monkeypatch):
    MockPaddleOCRClass.side_effect = Exception("Simulated PaddleOCR global init failure")
    img_bytes = create_minimal_png_bytes()
    result = get_image_metadata_with_paddleocr(img_bytes)
    assert isinstance(result, Err)
    assert "PaddleOCR initialization failed: Simulated PaddleOCR global init failure" in result.error

@patch('pdf_parser_py_lib.pdf_parser.extractor.PADDLEOCR_AVAILABLE', True)
@patch('pdf_parser_py_lib.pdf_parser.extractor.PaddleOCR')
def test_paddleocr_image_processing_failure(MockPaddleOCRClass):
    mock_ocr_instance = MagicMock()
    mock_ocr_instance.ocr.side_effect = Exception("Simulated PaddleOCR internal processing error")
    MockPaddleOCRClass.return_value = mock_ocr_instance # When PaddleOCR() is called, return this mock
    
    img_bytes = create_minimal_png_bytes()
    result = get_image_metadata_with_paddleocr(img_bytes)
    assert isinstance(result, Err)
    assert "PaddleOCR processing failed for image: Simulated PaddleOCR internal processing error" in result.error

@patch('pdf_parser_py_lib.pdf_parser.extractor.PADDLEOCR_AVAILABLE', True)
@patch('pdf_parser_py_lib.pdf_parser.extractor.Image.open') # Mock PIL's Image.open
def test_paddleocr_unidentified_image_error(mock_pil_image_open):
    mock_pil_image_open.side_effect = UnidentifiedImageError("Simulated bad image data")
    
    img_bytes = b"not_really_an_image"
    result = get_image_metadata_with_paddleocr(img_bytes)
    assert isinstance(result, Err)
    assert "Image processing failed for PaddleOCR: Image format not supported or image corrupt." in result.error
    assert "Simulated bad image data" in result.error


# extract_svg_from_page
@patch('fitz.Page.get_svg_image')
def test_extract_svg_runtime_error(mock_get_svg, pdf_with_vectors):
    mock_get_svg.side_effect = RuntimeError("Simulated SVG generation error")
    
    # To make this mock effective, we need to mock fitz.open and the doc/page structure
    mock_page_instance = MagicMock()
    mock_page_instance.get_svg_image.side_effect = RuntimeError("Simulated SVG generation error")
    mock_doc_instance = MagicMock()
    mock_doc_instance.page_count = 1
    mock_doc_instance.load_page.return_value = mock_page_instance

    with patch('fitz.open', return_value=mock_doc_instance):
        result = extract_svg_from_page(pdf_with_vectors, 0)
        assert isinstance(result, Err)
        assert "Failed to extract SVG from page 0: PyMuPDF runtime error." in result.error
        assert "Simulated SVG generation error" in result.error

# is_page_primarily_text (if used, needs robust error handling too)
@patch('pdf_parser_py_lib.pdf_parser.extractor.extract_text_from_pdf_page_direct')
def test_is_page_primarily_text_error_propagation(mock_direct_text_call):
    mock_direct_text_call.return_value = Err("Direct text extraction failed badly.")
    result = is_page_primarily_text("dummy.pdf", 0)
    assert isinstance(result, Err)
    assert "Could not determine if page is primarily text" in result.error
    assert "Direct text extraction failed badly." in result.error


# --- Keep some basic success tests to ensure functionality isn't broken by error handling additions ---
def test_direct_extract_success(text_pdf):
    result = extract_text_from_pdf_page_direct(text_pdf, 0)
    assert isinstance(result, Ok)
    assert "Direct text." in result.value

@patch('pdf_parser_py_lib.pdf_parser.extractor.PADDLEOCR_AVAILABLE', True)
@patch('pdf_parser_py_lib.pdf_parser.extractor.PaddleOCR', MockPaddleOCR)
def test_get_image_metadata_paddleocr_success_mocked(): # Renamed to avoid conflict
    img_bytes = create_minimal_png_bytes()
    result = get_image_metadata_with_paddleocr(img_bytes)
    assert isinstance(result, Ok)
    assert result.value["ocr_text"] == "Mocked Text"

def test_extract_svg_success(pdf_with_vectors):
    result = extract_svg_from_page(pdf_with_vectors, 0)
    assert isinstance(result, Ok)
    assert len(result.value) == 1 and "<svg" in result.value[0]

# ... (other existing success tests for other functions)The tests in `tests/test_extractor.py` have been updated to check for more specific error messages and to simulate various library failure scenarios.

Next, I will update `tests/test_html_generator.py` to ensure it correctly handles and displays page-level errors passed to `generate_page_html`.
