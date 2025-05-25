# This file makes Python treat the directory as a package.

from .extractor import (
    extract_text_from_pdf_page_direct,
    extract_text_with_ocr,
    determine_page_extraction_strategy,
    get_text_from_page,
    is_page_primarily_text,
    extract_tables_from_page,
    extract_images_from_page, 
    get_image_metadata_with_paddleocr,
    extract_svg_from_page, 
    Ok, 
    Err,
    PADDLEOCR_AVAILABLE 
)
from .html_generator import generate_page_html # Added
from .main import app # main.py will be refactored, but keep app export for now

__all__ = [
    # Extractor functions
    "extract_text_from_pdf_page_direct",
    "extract_text_with_ocr",
    "determine_page_extraction_strategy",
    "get_text_from_page",
    "is_page_primarily_text",
    "extract_tables_from_page",
    "extract_images_from_page", 
    "get_image_metadata_with_paddleocr", 
    "extract_svg_from_page", 
    
    # HTML Generator
    "generate_page_html", # Added

    # Result types and flags
    "Ok", 
    "Err",
    "PADDLEOCR_AVAILABLE",
    
    # FastAPI app (though main.py is being refactored, convention is to export app)
    "app" 
]
