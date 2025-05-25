import io
import time
from pathlib import Path
import os
import shutil

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.platypus import Table, TableStyle, Image as PlatypusImage, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus.flowables import KeepInFrame

from PIL import Image as PILImage, ImageDraw

# --- Reusable Test Helper: Wait for Job ---
# Moved from test_main.py for broader use
def wait_for_job_completion(job_id: str, jobs_dict: dict, timeout_seconds: int = 45) -> bool: # Increased timeout for integration tests
    """
    Waits for a job to reach 'completed' or 'error' status.
    Args:
        job_id: The ID of the job to check.
        jobs_dict: The dictionary where job statuses are stored (passed from test_main.jobs).
        timeout_seconds: How long to wait.
    Returns:
        True if the job completed or errored, False on timeout.
    """
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        if job_id not in jobs_dict:
            print(f"Job {job_id} disappeared from jobs_dict.")
            return False 
        status = jobs_dict[job_id].get("status")
        if status == "completed" or status == "error":
            print(f"Job {job_id} reached status: {status}")
            return True
        # print(f"Job {job_id} status: {status}, waiting...") # Verbose logging for CI
        time.sleep(0.5) # Slightly longer sleep for integration tests
    print(f"Job {job_id} timed out after {timeout_seconds}s. Last status: {jobs_dict.get(job_id, {}).get('status')}")
    return False


# --- PDF Generation Helpers ---

TEMP_PDF_DIR_BASE = Path("temp_generated_pdfs_for_integration_tests")

def _get_temp_pdf_path(name: str) -> str:
    """Creates a temporary directory for the test run if it doesn't exist, and returns a path within it."""
    if not TEMP_PDF_DIR_BASE.exists():
        TEMP_PDF_DIR_BASE.mkdir(parents=True, exist_ok=True)
    return str(TEMP_PDF_DIR_BASE / name)

def cleanup_temp_pdfs():
    """Removes the temporary PDF directory after tests."""
    if TEMP_PDF_DIR_BASE.exists():
        shutil.rmtree(TEMP_PDF_DIR_BASE)


def create_minimal_png_for_pdf(size=(100, 50), text="Embedded PNG") -> PlatypusImage:
    """Creates a Pillow Image, saves to BytesIO, then returns a ReportLab PlatypusImage."""
    pil_img = PILImage.new("RGB", size, color="lightblue")
    draw = ImageDraw.Draw(pil_img)
    try:
        # Basic text drawing, no specific font needed for this small image
        draw.text((10, 10), text, fill="black")
    except Exception as e:
        print(f"Warning: Could not draw text on image for PDF: {e}") # Might fail in minimal envs

    img_byte_io = io.BytesIO()
    pil_img.save(img_byte_io, format="PNG")
    img_byte_io.seek(0) # Reset stream position
    return PlatypusImage(img_byte_io, width=size[0]*0.75, height=size[1]*0.75) # Scale for points

# 1. Multi-page PDF with mixed text and images
def generate_pdf_multi_page_mixed_content(filename: str = "multi_page_mixed.pdf") -> str:
    path = _get_temp_pdf_path(filename)
    c = canvas.Canvas(path, pagesize=letter)
    styles = getSampleStyleSheet()
    normal_style = styles['Normal']

    # Page 1
    c.drawString(1*inch, 7.5*inch, "Page 1: Introduction")
    p1_text = Paragraph("This is the first page with some introductory text. It demonstrates basic text rendering and layout capabilities of ReportLab. We will include an image below.", normal_style)
    p1_text.wrapOn(c, 6*inch, 1*inch)
    p1_text.drawOn(c, 1*inch, 6.5*inch)
    img1 = create_minimal_png_for_pdf(text="Image on Page 1")
    img1.drawOn(c, 1*inch, 4*inch)
    c.showPage()

    # Page 2
    c.drawString(1*inch, 7.5*inch, "Page 2: More Details and Another Image")
    p2_text = Paragraph("This second page contains more textual information, possibly spanning multiple paragraphs. ReportLab allows for complex document structures. Here is another image, perhaps smaller.", normal_style)
    p2_text.wrapOn(c, 6*inch, 1*inch)
    p2_text.drawOn(c, 1*inch, 6.5*inch)
    img2 = create_minimal_png_for_pdf(size=(80,40), text="Small Img Page 2")
    img2.drawOn(c, 1*inch, 5*inch)
    c.showPage()
    
    # Page 3 (Text only)
    c.drawString(1*inch, 7.5*inch, "Page 3: Text-Only Page")
    p3_text = Paragraph("This page is dedicated to text to check how purely textual pages are processed. This might be useful for testing direct text extraction versus OCR strategies if the text were an image.", normal_style)
    p3_text.wrapOn(c, 6*inch, 2*inch)
    p3_text.drawOn(c, 1*inch, 5*inch)
    c.showPage()

    c.save()
    return path

# 2. PDF page containing a complex table (simulated)
def generate_pdf_complex_table(filename: str = "complex_table.pdf") -> str:
    path = _get_temp_pdf_path(filename)
    c = canvas.Canvas(path, pagesize=letter)
    c.drawString(1*inch, 7.5*inch, "Complex Table Simulation")

    # Data with some longer content and varied lengths
    data = [
        ["ID", "Product Name", "Description", "Price"],
        ["001", "Super Widget", "An amazing widget that does everything you can imagine and more!", "$99.99"],
        ["002", "Basic Gadget", "A simple gadget for everyday tasks. Reliable and sturdy.", "$19.50"],
        ["003", "Advanced Gizmo", "State-of-the-art gizmo with AI features. Requires subscription.", "$299.00 (monthly)"],
        ["004", "Tiny Thingamajig", "A very small but useful thingamajig.", "$5.00"]
    ]
    
    # Column widths - making 'Description' wider
    col_widths = [0.5*inch, 1.5*inch, 3.5*inch, 1*inch]
    
    table = Table(data, colWidths=col_widths)
    style = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
        ('ALIGN',(0,0),(-1,-1),'LEFT'), # Left align for text
        ('ALIGN', (0,0), (0,-1), 'CENTER'), # Center align for ID
        ('ALIGN', (-1,0), (-1,-1), 'RIGHT'), # Right align for Price
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8), # Smaller font for more content
        ('BOTTOMPADDING', (0,0), (-1,0), 10),
        ('BACKGROUND',(0,1),(-1,-1),colors.beige),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        # Spanning example (ReportLab makes true merged cells a bit complex without deeper Platypus flowables)
        # For a simple Canvas-based table, we might simulate by drawing lines carefully or just accept limitations.
        # This example does not include cell spanning for simplicity with basic Table.
        # ('SPAN', (0,4), (2,4)), # Example: Span first 3 cells of a hypothetical 5th row
    ])
    table.setStyle(style)
    
    # Wrap and draw
    table.wrapOn(c, 7*inch, 5*inch)
    table.drawOn(c, 1*inch, 4*inch)
    c.showPage()
    c.save()
    return path

# 3. PDF page that is primarily a scanned image (simulated)
def generate_pdf_scanned_image_page(filename: str = "scanned_image_page.pdf", text_on_image="Scanned Document Text") -> str:
    path = _get_temp_pdf_path(filename)
    c = canvas.Canvas(path, pagesize=letter) # Portrait
    
    # Create a large image that covers most of the page
    # Page size in points: letter is (612, 792)
    # Leave some margin
    img_width_pts = 580 
    img_height_pts = 760
    
    pil_img = PILImage.new("L", (img_width_pts, img_height_pts), color="white") # Grayscale
    draw = ImageDraw.Draw(pil_img)
    # Simulate some text on the image that would require OCR
    # For a real test, this text should be somewhat complex or slightly degraded
    draw.text((50, 50), text_on_image, fill="black")
    draw.text((50, 100), "Another line of text for OCR.", fill="black")
    draw.line([(50,150),(530,150)], fill="black", width=2) # A line

    img_byte_io = io.BytesIO()
    pil_img.save(img_byte_io, format="PNG") # PNG or TIFF are common for scans
    img_byte_io.seek(0)
    
    # Embed the image directly onto the canvas, covering most of the page
    # ReportLab's drawImage uses points for x,y,width,height
    c.drawImage(ImageReader(img_byte_io), 16, 16, width=img_width_pts, height=img_height_pts) # (0,0) is bottom-left
    
    c.showPage()
    c.save()
    return path

# 4. PDF with simple vector graphics and text
def generate_pdf_vector_graphics_and_text(filename: str = "vector_text.pdf") -> str:
    path = _get_temp_pdf_path(filename)
    c = canvas.Canvas(path, pagesize=letter)
    styles = getSampleStyleSheet()
    
    c.drawString(1*inch, 7.5*inch, "Page with Vector Graphics and Text")
    
    # Text
    p_text = Paragraph("This page contains both text elements, like this paragraph, and vector graphics drawn directly onto the PDF canvas using ReportLab's drawing methods. The SVG extraction should capture these vector elements.", styles['Normal'])
    p_text.wrapOn(c, 6*inch, 1.5*inch)
    p_text.drawOn(c, 1*inch, 6*inch)

    # Vector Graphics
    c.setStrokeColor(colors.blue)
    c.setFillColor(colors.lightblue)
    c.rect(1*inch, 4*inch, 2*inch, 1.5*inch, stroke=1, fill=1) # Filled rectangle
    
    c.setStrokeColor(colors.red)
    c.line(3.5*inch, 4*inch, 5.5*inch, 5.5*inch) # Line
    
    c.setFillColor(colors.lightgreen)
    c.circle(4.5*inch, 3*inch, 0.5*inch, stroke=1, fill=1) # Filled circle
    
    c.showPage()
    c.save()
    return path

# 5. PDF with multi-column text layout (simulated)
def generate_pdf_multi_column_text(filename: str = "multi_column.pdf") -> str:
    path = _get_temp_pdf_path(filename)
    c = canvas.Canvas(path, pagesize=letter)
    styles = getSampleStyleSheet()
    normal_style = styles['Normal']

    c.drawString(1*inch, 7.5*inch, "Multi-Column Text Simulation")

    col1_x, col2_x = 1*inch, 4.25*inch # Start X for each column
    col_width = 3*inch
    col_height = 6*inch
    y_pos = 1*inch # Bottom Y for the frame

    text_col1 = """This is the first column. It contains a block of text that should be processed primarily by direct text extraction. The layout might pose a challenge for simple line-by-line concatenation if not handled carefully by the extraction logic. Multiple sentences are here. This is the end of column one text.""" * 3
    text_col2 = """This is the second column, placed to the right of the first. It serves to test how the PDF parser handles text that is not in a single continuous block down the page. This text is also repeated for volume. This is the end of column two content.""" * 3
    
    # Using Platypus Frames and Paragraphs for better column simulation
    frame1 = Frame(col1_x, y_pos, col_width, col_height, id='col1', showBoundary=0) # Set showBoundary=1 for debugging
    frame2 = Frame(col2_x, y_pos, col_width, col_height, id='col2', showBoundary=0)
    
    story1 = [Paragraph(text_col1, normal_style)]
    story2 = [Paragraph(text_col2, normal_style)]

    # KeepInFrame is used to ensure content fits or is truncated, rather than flowing off.
    # For this test, we assume content fits.
    frame1.addFromList(story1, c)
    frame2.addFromList(story2, c)
    
    c.showPage()
    c.save()
    return path

# List of all generator functions for easy iteration in tests or setup
ALL_PDF_GENERATORS = [
    generate_pdf_multi_page_mixed_content,
    generate_pdf_complex_table,
    generate_pdf_scanned_image_page,
    generate_pdf_vector_graphics_and_text,
    generate_pdf_multi_column_text,
]

if __name__ == '__main__':
    # Example of generating all PDFs
    print(f"Generating test PDFs in: {TEMP_PDF_DIR_BASE.resolve()}")
    if TEMP_PDF_DIR_BASE.exists():
        shutil.rmtree(TEMP_PDF_DIR_BASE) # Clean before generating
    TEMP_PDF_DIR_BASE.mkdir(parents=True, exist_ok=True)

    paths = []
    for generator_func in ALL_PDF_GENERATORS:
        pdf_path = generator_func() # Uses default filename
        paths.append(pdf_path)
        print(f"Generated: {pdf_path}")
    
    print("\nGenerated PDF paths:")
    for p in paths: print(p)
    # To clean up after manual generation: cleanup_temp_pdfs()
    # cleanup_temp_pdfs()
    # print(f"\nCleaned up: {TEMP_PDF_DIR_BASE}")
