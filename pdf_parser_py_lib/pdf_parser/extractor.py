import fitz  # PyMuPDF
import pytesseract
from PIL import Image, UnidentifiedImageError
import io
import camelot
import pandas as pd
from typing import TypeVar, Union, List, Dict, Tuple, Any 
import logging

# --- Basic Logging Setup ---
# It's good practice to configure logging at the application entry point (e.g., main.py or a config module)
# For now, setting up a basic logger for this module.
logger = logging.getLogger(__name__)
# Example: if __name__ == '__main__': # Or in your app startup
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


try:
    from paddleocr import PaddleOCR
    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False
    logger.warning("PaddleOCR library not found. OCR functionalities via PaddleOCR will be disabled.")
    class PaddleOCR: # Stub class
        def __init__(self, **kwargs): 
            logger.info("Stubbed PaddleOCR initialized (PaddleOCR library not available).")
        def ocr(self, img_bytes, cls=True): 
            logger.warning("Stubbed PaddleOCR ocr called (PaddleOCR library not available).")
            return [[([], ('PaddleOCR not available', 0.0))]] 

# --- Result Type Definition ---
T = TypeVar('T')
E = TypeVar('E') # Represents an error type, currently string
class Ok:
    def __init__(self, value: T): self.value = value
    def __repr__(self): return f"Ok({self.value!r})"
class Err:
    def __init__(self, error: E): self.error = error # error is a string message
    def __repr__(self): return f"Err({self.error!r})"
Result = Union[Ok[T], Err[E]]

# --- Core Extraction Functions with Enhanced Error Handling ---

def extract_text_from_pdf_page_direct(pdf_path: str, page_number: int) -> Result[str, str]:
    doc = None
    try: 
        doc = fitz.open(pdf_path)
    except fitz.fitz.PyMuPDFError as e: # More specific PyMuPDF error
        logger.error(f"PyMuPDFError opening '{pdf_path}': {e}", exc_info=True)
        return Err(f"Failed to open PDF (direct text extraction): Possible corruption or encryption. Details: {e}")
    except Exception as e: 
        logger.error(f"Generic error opening '{pdf_path}' for direct text: {e}", exc_info=True)
        return Err(f"Failed to open PDF (direct text extraction): {e}")
    
    if not (0 <= page_number < doc.page_count): 
        doc.close()
        return Err(f"Page number {page_number} is out of range (0-{doc.page_count - 1}).")
    
    try: 
        page = doc.load_page(page_number)
        text = page.get_text("text")
        doc.close()
        return Ok(text if text else "")
    except RuntimeError as e: # Catch specific runtime errors from PyMuPDF if any during text extraction
        logger.error(f"RuntimeError extracting direct text from page {page_number} of '{pdf_path}': {e}", exc_info=True)
        doc.close()
        return Err(f"Failed to extract direct text from page {page_number}: PyMuPDF runtime error. Details: {e}")
    except Exception as e: 
        logger.error(f"Generic error extracting direct text from page {page_number} of '{pdf_path}': {e}", exc_info=True)
        doc.close()
        return Err(f"Failed to extract direct text from page {page_number}: {e}")

def extract_text_with_ocr(pdf_path: str, page_number: int) -> Result[str, str]: # Tesseract based
    doc = None
    try: 
        doc = fitz.open(pdf_path)
    except fitz.fitz.PyMuPDFError as e:
        logger.error(f"PyMuPDFError opening '{pdf_path}' for Tesseract OCR prep: {e}", exc_info=True)
        return Err(f"Failed to open PDF (for Tesseract OCR): Possible corruption or encryption. Details: {e}")
    except Exception as e: 
        logger.error(f"Generic error opening '{pdf_path}' for Tesseract OCR prep: {e}", exc_info=True)
        return Err(f"Failed to open PDF (for Tesseract OCR): {e}")

    if not (0 <= page_number < doc.page_count): 
        doc.close()
        return Err(f"Page number {page_number} is out of range for Tesseract OCR (0-{doc.page_count - 1}).")
    
    try:
        page = doc.load_page(page_number)
        # Higher DPI for better OCR, but watch performance
        pix = page.get_pixmap(dpi=300, alpha=False) # alpha=False for non-transparent RGB
        img_byte_arr = pix.tobytes("png")
        image = Image.open(io.BytesIO(img_byte_arr))
        text = pytesseract.image_to_string(image)
        doc.close()
        return Ok(text)
    except pytesseract.TesseractNotFoundError:
        logger.error("Tesseract command not found.", exc_info=True)
        if doc: doc.close()
        return Err("Tesseract command not found or not configured correctly in system PATH.")
    except pytesseract.TesseractError as e: # More specific Tesseract error
        logger.error(f"TesseractError on page {page_number} of '{pdf_path}': {e}", exc_info=True)
        if doc: doc.close()
        return Err(f"Tesseract OCR processing failed for page {page_number}: {e}")
    except RuntimeError as e: # Catch PyMuPDF runtime errors during pixmap generation etc.
        logger.error(f"RuntimeError during Tesseract prep for page {page_number} of '{pdf_path}': {e}", exc_info=True)
        if doc: doc.close()
        return Err(f"Failed Tesseract OCR prep for page {page_number}: PyMuPDF runtime error. Details: {e}")
    except Exception as e: 
        logger.error(f"Generic error during Tesseract OCR for page {page_number} of '{pdf_path}': {e}", exc_info=True)
        if doc: doc.close()
        return Err(f"Failed Tesseract OCR extraction on page {page_number}: {e}")

def determine_page_extraction_strategy(
    pdf_path: str, 
    page_number: int, 
    text_threshold: int = 100, 
    ocr_threshold: int = 50 
) -> Result[str, str]:
    direct_text_result = extract_text_from_pdf_page_direct(pdf_path, page_number)
    if isinstance(direct_text_result, Err): 
        # Propagate error, but could add context if needed:
        # return Err(f"Strategy determination failed due to error in direct text extraction: {direct_text_result.error}")
        return direct_text_result 

    direct_text = direct_text_result.value
    if len(direct_text.strip()) >= text_threshold: 
        return Ok("direct")

    doc = None
    try:
        doc = fitz.open(pdf_path)
        if not (0 <= page_number < doc.page_count): 
             # This check is also in extract_text_from_pdf_page_direct, but good for safety if called independently
            return Err(f"Page number {page_number} out of range for strategy determination.")
        page = doc.load_page(page_number)
        has_images = bool(page.get_images(full=True))
        doc.close()
    except fitz.fitz.PyMuPDFError as e:
        logger.error(f"PyMuPDFError analyzing images on page {page_number} of '{pdf_path}' for strategy: {e}", exc_info=True)
        if doc and doc.is_open: doc.close()
        return Err(f"Failed to analyze page for images (strategy determination): PyMuPDF error. Details: {e}")
    except Exception as e: 
        logger.error(f"Generic error analyzing images on page {page_number} of '{pdf_path}' for strategy: {e}", exc_info=True)
        if doc and doc.is_open: doc.close()
        return Err(f"Failed to analyze page for images (strategy determination): {e}")

    # Heuristic for choosing OCR: if direct text is very sparse, or if images are present.
    if has_images or len(direct_text.strip()) < (text_threshold / 2): # Example heuristic
        return Ok("ocr") 

    # If direct text is not substantial, and OCR wasn't strongly indicated by images or very sparse text
    if len(direct_text.strip()) < ocr_threshold: 
        return Ok("low_confidence")
    
    return Ok("direct") # Default fallback if some text exists but not meeting 'text_threshold'

def get_text_from_page(
    pdf_path: str, 
    page_number: int, 
    text_threshold: int = 100, 
    ocr_threshold: int = 50
) -> Result[str, str]:
    strategy_result = determine_page_extraction_strategy(pdf_path, page_number, text_threshold, ocr_threshold)
    if isinstance(strategy_result, Err): 
        return Err(f"Could not determine text extraction strategy: {strategy_result.error}") # Add context
    
    strategy = strategy_result.value
    if strategy == "direct": 
        return extract_text_from_pdf_page_direct(pdf_path, page_number)
    
    if strategy == "ocr": # Tesseract OCR
        ocr_result = extract_text_with_ocr(pdf_path, page_number) # Tesseract
        if isinstance(ocr_result, Ok):
            if len(ocr_result.value.strip()) >= ocr_threshold: 
                return ocr_result
            # Fallback for weak OCR: check direct text again
            direct_result = extract_text_from_pdf_page_direct(pdf_path, page_number) # Avoid re-calling if already have from strategy
            if isinstance(direct_result, Ok) and len(direct_result.value.strip()) > len(ocr_result.value.strip()):
                return direct_result 
            return Ok(f"Low confidence Tesseract OCR: '{ocr_result.value[:100].strip()}...' (Direct text also sparse or unavailable).") 
        return ocr_result # Propagate Tesseract OCR error
        
    if strategy == "low_confidence":
        direct_text_result = extract_text_from_pdf_page_direct(pdf_path, page_number)
        if isinstance(direct_text_result, Ok) and len(direct_text_result.value.strip()) > 0 :
             return Ok(f"Low confidence text extraction (direct attempt): '{direct_text_result.value[:100].strip()}...'")
        return Ok("Low confidence: No significant text found via direct or OCR methods.")
    
    return Err(f"Unknown text extraction strategy: {strategy}")

def extract_tables_from_page(pdf_path: str, page_number: int) -> Result[List[str], str]:
    camelot_page_str = str(page_number + 1) 
    try:
        # It's important that Camelot's dependencies (Ghostscript, OpenCV, tk) are correctly installed.
        tables = camelot.read_pdf(
            filepath=pdf_path, 
            pages=camelot_page_str, 
            flavor='lattice', # 'lattice' for tables with lines. 'stream' for tables without clear lines.
            suppress_stdout=True # Suppress Camelot's own logging to stdout
        )
        html_tables: List[str] = [table.df.to_html(index=False, border=1, escape=True) for table in tables]
        return Ok(html_tables)
    except FileNotFoundError as e: # Example: Ghostscript not found
        logger.error(f"FileNotFoundError during Camelot processing for page {page_number} of '{pdf_path}': {e}. This might be a Ghostscript/dependency issue.", exc_info=True)
        return Err(f"Table extraction failed: Essential dependency (like Ghostscript) not found. Details: {e}")
    except Exception as e: # Catching a broad exception as Camelot can raise various internal errors
        logger.error(f"Camelot processing error for page {page_number} of '{pdf_path}': {e}", exc_info=True)
        error_message = f"Table extraction with Camelot failed for page {page_number}. Details: {e}"
        # Check for common Camelot/dependency issues in the error message
        if "ghostscript" in str(e).lower():
            error_message = f"Table extraction failed: Ghostscript error. Ensure Ghostscript is installed and in PATH. Original error: {e}"
        elif "opencv" in str(e).lower() or "cv2" in str(e).lower():
            error_message = f"Table extraction failed: OpenCV error. Ensure OpenCV is correctly installed for Camelot. Original error: {e}"
        return Err(error_message)

ImageInfo = Dict[str, Any] 
def extract_images_from_page(pdf_path: str, page_number: int) -> Result[List[ImageInfo], str]:
    images_on_page: List[ImageInfo] = []
    doc = None
    try: 
        doc = fitz.open(pdf_path)
    except fitz.fitz.PyMuPDFError as e:
        logger.error(f"PyMuPDFError opening '{pdf_path}' for image extraction: {e}", exc_info=True)
        return Err(f"Failed to open PDF for image extraction: Possible corruption or encryption. Details: {e}")
    except Exception as e: 
        logger.error(f"Generic error opening '{pdf_path}' for image extraction: {e}", exc_info=True)
        return Err(f"Failed to open PDF for image extraction: {e}")

    if not (0 <= page_number < doc.page_count): 
        if doc: doc.close()
        return Err(f"Page number {page_number} is out of range for image extraction (0-{doc.page_count - 1}).")

    try:
        page = doc.load_page(page_number)
        raw_image_list = page.get_images(full=True)
        if not raw_image_list: 
            doc.close()
            return Ok([]) 

        for img_info_tuple in raw_image_list:
            xref = img_info_tuple[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception as e_extract: # PyMuPDF can raise error if image is malformed for this xref
                logger.warning(f"Could not extract image for xref {xref} on page {page_number} of '{pdf_path}': {e_extract}", exc_info=True)
                images_on_page.append({
                    "image_bytes": None, "format": "unknown", "bbox": "unknown", "xref": xref,
                    "error": f"Failed to extract image bytes for xref {xref}: {e_extract}"
                })
                continue

            if not base_image: 
                logger.warning(f"Extracted image for xref {xref} on page {page_number} of '{pdf_path}' was None.")
                images_on_page.append({
                    "image_bytes": None, "format": "unknown", "bbox": "unknown", "xref": xref,
                    "error": f"Extracted image for xref {xref} was None."
                })
                continue
            
            image_bytes = base_image["image"]
            image_format = base_image["ext"]
            
            found_bbox = None
            # Finding specific bbox for an image instance can be complex.
            # page.get_image_rects(base_image["xref"]) or iterating drawings.
            # For now, this simplified approach from previous step:
            for item in page.get_drawings(): 
                if item["type"] == "image" and item.get("xref") == xref:
                    found_bbox = item["rect"] 
                    break
            
            bbox_tuple: Union[Tuple[float, float, float, float], str] = "Not directly found"
            if found_bbox:
                 bbox_tuple = (found_bbox.x0, found_bbox.y0, found_bbox.x1, found_bbox.y1)

            images_on_page.append({
                "image_bytes": image_bytes, "format": image_format, 
                "bbox": bbox_tuple, "xref": xref, "error": None
            })
        
        doc.close()
        return Ok(images_on_page)
    except RuntimeError as e: # Catch PyMuPDF runtime errors
        logger.error(f"RuntimeError extracting images from page {page_number} of '{pdf_path}': {e}", exc_info=True)
        if doc and doc.is_open: doc.close()
        return Err(f"Failed to extract images from page {page_number}: PyMuPDF runtime error. Details: {e}")
    except Exception as e:
        logger.error(f"Generic error extracting images from page {page_number} of '{pdf_path}': {e}", exc_info=True)
        if doc and doc.is_open: doc.close()
        return Err(f"Failed to extract images from page {page_number}: {e}")

def get_image_metadata_with_paddleocr(image_bytes: bytes) -> Result[Dict[str, Any], str]:
    if not PADDLEOCR_AVAILABLE: 
        return Err("PaddleOCR is not installed or available. Cannot perform OCR on image.")

    ocr_tool = None
    try:
        # For production, this instance should be global and reused.
        ocr_tool = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False, show_log=False)
    except Exception as e:
        logger.error(f"Failed to initialize PaddleOCR: {e}", exc_info=True)
        return Err(f"PaddleOCR initialization failed: {e}")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert to RGB if it's RGBA or P (palette) to avoid issues with some OCR backends
        if img.mode == 'RGBA' or img.mode == 'P': img = img.convert('RGB')
        
        import numpy as np # PaddleOCR expects numpy array
        img_np = np.array(img)
        
        # Perform OCR
        ocr_result = ocr_tool.ocr(img_np, cls=True) # cls for text angle classification
        
        detected_lines_data = []
        all_text_parts = []
        # Ensure ocr_result and its first element are not None before iterating
        if ocr_result and ocr_result[0] is not None: 
            for line_info in ocr_result[0]: 
                # line_info is typically [[points], (text, confidence)]
                if line_info and len(line_info) == 2:
                    points, (text, confidence) = line_info[0], line_info[1]
                    detected_lines_data.append({
                        "text": text, "confidence": confidence, "bbox_polygon": points
                    })
                    all_text_parts.append(text)
        
        full_ocr_text = " ".join(all_text_parts)
        summary = ""
        if all_text_parts:
            summary = f"Image contains text: '{all_text_parts[0][:50].strip()}...'" if len(all_text_parts[0]) > 50 else f"Image contains text: '{all_text_parts[0].strip()}'"

        return Ok({
            "ocr_text": full_ocr_text, "detected_lines": detected_lines_data, "summary": summary
        })
    except UnidentifiedImageError as e: # PIL error for corrupted/unsupported image formats
        logger.error(f"PIL UnidentifiedImageError during PaddleOCR prep: {e}", exc_info=True)
        return Err(f"Image processing failed for PaddleOCR: Image format not supported or image corrupt. Details: {e}")
    except Exception as e:
        logger.error(f"PaddleOCR failed to process image: {e}", exc_info=True)
        return Err(f"PaddleOCR processing failed for image: {e}")

def extract_svg_from_page(pdf_path: str, page_number: int) -> Result[List[str], str]:
    doc = None
    try:
        doc = fitz.open(pdf_path)
    except fitz.fitz.PyMuPDFError as e:
        logger.error(f"PyMuPDFError opening '{pdf_path}' for SVG extraction: {e}", exc_info=True)
        return Err(f"Failed to open PDF for SVG extraction: Possible corruption or encryption. Details: {e}")
    except Exception as e:
        logger.error(f"Generic error opening '{pdf_path}' for SVG extraction: {e}", exc_info=True)
        return Err(f"Failed to open PDF for SVG extraction: {e}")

    if not (0 <= page_number < doc.page_count):
        if doc: doc.close()
        return Err(f"Page number {page_number} is out of range for SVG extraction (0-{doc.page_count - 1}).")

    try:
        page = doc.load_page(page_number)
        # matrix=fitz.Identity means no transformation (scaling, rotation)
        svg_text = page.get_svg_image(matrix=fitz.Identity)
        doc.close()

        if not svg_text or svg_text.isspace(): 
            return Ok([]) 
        
        # Heuristic for "empty" SVG (e.g., only contains <svg> wrapper with no actual drawing elements)
        # This can be refined by parsing the SVG with an XML parser for more accuracy.
        # For now, a length check and absence of common drawing tags.
        # Common drawing tags: path, rect, circle, line, polygon, text, image, use, g (group)
        drawing_tags = ["<path", "<rect", "<circle", "<line", "<polygon", "<text", "<image", "<use", "<g "]
        if len(svg_text) < 250 and not any(tag in svg_text for tag in drawing_tags):
             logger.info(f"SVG content for page {page_number} of '{pdf_path}' appears empty or trivial, returning empty list.")
             return Ok([])

        return Ok([svg_text]) 
    except RuntimeError as e: # Catch PyMuPDF runtime errors
        logger.error(f"RuntimeError extracting SVG from page {page_number} of '{pdf_path}': {e}", exc_info=True)
        if doc and doc.is_open: doc.close()
        return Err(f"Failed to extract SVG from page {page_number}: PyMuPDF runtime error. Details: {e}")
    except Exception as e:
        logger.error(f"Generic error extracting SVG from page {page_number} of '{pdf_path}': {e}", exc_info=True)
        if doc and doc.is_open: doc.close()
        return Err(f"Failed to extract SVG from page {page_number}: {e}")

# --- is_page_primarily_text (kept for now, review its necessity later) ---
def is_page_primarily_text(pdf_path: str, page_number: int, text_threshold_chars: int = 100) -> Result[bool, str]:
    extraction_result = extract_text_from_pdf_page_direct(pdf_path, page_number)
    if isinstance(extraction_result, Ok):
        text = extraction_result.value
        return Ok(len(text.strip()) >= text_threshold_chars)
    # Propagate the error from direct text extraction
    return Err(f"Could not determine if page is primarily text due to error in direct text extraction: {extraction_result.error}")
