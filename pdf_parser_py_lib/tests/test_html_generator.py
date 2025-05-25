import pytest
from pdf_parser_py_lib.pdf_parser.html_generator import generate_page_html
import html # For checking escaped error messages

def test_generate_page_html_all_elements_and_errors():
    page_data = {
        "page_number": 1,
        "text": "Hello World!\nThis is a new line.",
        "tables": ["<table><tr><td>Table 1</td></tr></table>"],
        "images_metadata": [
            {
                "format": "png", "xref": 123, "bbox": (0,0,10,10),
                "metadata": {"ocr_text": "Image OCR Text 1", "summary": "Summary 1"}
            },
            {
                "format": "jpeg", "xref": 456, "bbox": (20,20,30,30),
                "metadata_error": "OCR failed for this image."
            },
            {
                "format": "gif", "xref": 789, "bbox": (40,40,50,50),
                "error": "Failed to extract this image's bytes." # Error from image extraction itself
            }
        ],
        "svg_graphics": ["<svg><rect x='0' y='0' width='10' height='10'/></svg>"],
        "errors": [
            "Page-level error 1: Something went wrong with text.", 
            "Page-level error 2: <Another issue>"
        ]
    }
    html_content = generate_page_html(page_data)

    # Check for page-level errors display
    assert "<div style='border: 2px solid red; padding: 10px; margin-bottom: 15px;'>" in html_content
    assert "<h3>Processing Errors on this Page:</h3>" in html_content
    assert f"<li>{html.escape('Page-level error 1: Something went wrong with text.')}</li>" in html_content
    assert f"<li>{html.escape('Page-level error 2: <Another issue>')}</li>" in html_content

    # Check other elements (as in previous tests)
    assert "<h1>Page 1</h1>" in html_content
    assert "<h2>Extracted Text</h2>" in html_content
    # Text might be an error message itself if text extraction failed and was also added to page_data["text"]
    # The current html_generator logic tries to avoid duplicating error messages if text content IS an error.
    # If text_content is "Error extracting text:...", it will be displayed as such.
    # If text_content is normal, but there's an error in page_data["errors"] related to text, it's fine.
    assert "<p>Hello World!<br>This is a new line.</p>" in html_content 
    
    assert "<h2>Extracted Tables</h2>" in html_content
    assert "<h4>Table 1</h4><table><tr><td>Table 1</td></tr></table>" in html_content
    
    assert "<h2>Extracted Images</h2>" in html_content
    # Image 1 (Successful OCR)
    assert "<h4>Image 1 (Format: png) (XRef: 123)</h4>" in html_content
    assert "[Image Placeholder for Image 1 (Format: png) (XRef: 123)]" in html_content
    assert "<h5>Image OCR Text:</h5><p>Image OCR Text 1</p>" in html_content
    # Image 2 (OCR Metadata Error)
    assert "<h4>Image 2 (Format: jpeg) (XRef: 456)</h4>" in html_content
    assert "<h5>Image OCR Text:</h5><p><span style='color:red;'>Could not get OCR metadata: OCR failed for this image.</span></p>" in html_content
    # Image 3 (Image Extraction Error)
    assert "<h4>Image 3 (Format: gif) (XRef: 789)</h4>" in html_content
    assert "<p style='color:red;'>Error extracting this image: Failed to extract this image's bytes.</p>" in html_content


    assert "<h2>Extracted SVG Graphics</h2>" in html_content
    assert "<h4>SVG Graphic 1</h4>" in html_content
    assert "<pre style='border:1px solid #ccc; padding:5px; max-height:150px; overflow:auto;'>&lt;svg&gt;&lt;rect x='0' y='0' width='10' height='10'/&gt;&lt;/svg&gt;</pre>" in html_content


def test_generate_page_html_only_page_errors():
    page_data = {
        "page_number": "ErrorPage",
        "text": None, "tables": None, "images_metadata": None, "svg_graphics": None,
        "errors": ["Critical failure for this page.", "Another <problem>."]
    }
    html_content = generate_page_html(page_data)
    assert "<h1>Page ErrorPage</h1>" in html_content
    assert "<h3>Processing Errors on this Page:</h3>" in html_content
    assert f"<li>{html.escape('Critical failure for this page.')}</li>" in html_content
    assert f"<li>{html.escape('Another <problem>.')}</li>" in html_content
    # Check that other sections show "no data" or error messages if applicable
    assert "<h2>Extracted Text</h2><p>No significant text extracted or an error occurred (see errors above if any).</p>" in html_content
    # Check if sections mention errors if their specific error messages are in page_errors
    assert "<h2>Extracted Tables</h2><p style='color:red;'>Table extraction failed (see errors above).</p>" not in html_content # No specific table error
    assert "<h2>Extracted Images</h2><p style='color:red;'>Image extraction failed (see errors above).</p>" not in html_content # No specific image error


def test_generate_page_html_text_is_error_message():
    page_data = {
        "page_number": 10,
        "text": "Error extracting text: Corrupted text layer.", # Text itself is an error message
        "tables": [], "images_metadata": [], "svg_graphics": [],
        "errors": ["Text extraction failed: Corrupted text layer."] # The error is also in the page errors list
    }
    html_content = generate_page_html(page_data)
    assert "<h3>Processing Errors on this Page:</h3>" in html_content
    assert f"<li>{html.escape('Text extraction failed: Corrupted text layer.')}</li>" in html_content
    # The html_generator might display the error message from page_data["text"] directly
    # or rely on the errors list. Current logic: if text content contains "Error extracting text:", it's styled red.
    assert "<p style='color:red;'>Error extracting text: Corrupted text layer.</p>" in html_content


def test_generate_page_html_specific_extraction_failures_in_errors_list():
    page_data = {
        "page_number": 11,
        "text": "Some text was found.",
        "tables": None, # No tables successfully extracted
        "images_metadata": None, # No images successfully extracted
        "svg_graphics": None, # No SVGs successfully extracted
        "errors": [
            "Table extraction failed: Camelot internal error.",
            "Image extraction failed: Could not decode image stream.",
            "SVG extraction failed: PyMuPDF SVG generation issue."
        ]
    }
    html_content = generate_page_html(page_data)
    assert "<h3>Processing Errors on this Page:</h3>" in html_content
    assert "<li>Table extraction failed: Camelot internal error.</li>" in html_content
    assert "<li>Image extraction failed: Could not decode image stream.</li>" in html_content
    assert "<li>SVG extraction failed: PyMuPDF SVG generation issue.</li>" in html_content

    assert "<h2>Extracted Text</h2><p>Some text was found.</p>" in html_content
    assert "<h2>Extracted Tables</h2><p style='color:red;'>Table extraction failed (see errors above).</p>" in html_content
    assert "<h2>Extracted Images</h2><p style='color:red;'>Image extraction failed (see errors above).</p>" in html_content
    assert "<h2>Extracted SVG Graphics</h2><p style='color:red;'>SVG extraction failed (see errors above).</p>" in html_content

# Keep existing tests for other functionalities to ensure no regressions
def test_generate_page_html_only_text(): # Original test from previous step
    page_data = {
        "page_number": 2,
        "text": "Only text here.\n\nTwo newlines.",
        "tables": [], "images_metadata": [], "svg_graphics": [], "errors": []
    }
    html_content = generate_page_html(page_data)
    assert "<h1>Page 2</h1>" in html_content
    assert "<p>Only text here.<br><br>Two newlines.</p>" in html_content
    assert "<h2>Extracted Tables</h2>" not in html_content
    assert "<h2>Extracted Images</h2>" not in html_content
    assert "<h2>Extracted SVG Graphics</h2>" not in html_content
    assert "<h3>Processing Errors on this Page:</h3>" not in html_content

def test_generate_page_html_empty_data(): # Original test from previous step
    page_data = {
        "page_number": "N/A", "text": None, "tables": None, 
        "images_metadata": None, "svg_graphics": None, "errors": None # errors can be None
    }
    html_content = generate_page_html(page_data)
    assert "<h1>Page N/A</h1>" in html_content
    assert "<h2>Extracted Text</h2><p>No significant text extracted or an error occurred (see errors above if any).</p>" in html_content
    assert "<h3>Processing Errors on this Page:</h3>" not in html_content # No errors section if errors is None/empty
```
