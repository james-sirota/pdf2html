from typing import Dict, List, Any
import html

def generate_page_html(page_data: Dict[str, Any]) -> str:
    """
    Generates a single HTML string representation for a processed PDF page.

    Args:
        page_data: A dictionary containing the extracted data for a single page.
                   Expected keys: "page_number", "text", "tables", "images_metadata", 
                                  "svg_graphics", and "errors".
                   - "page_number": int | str
                   - "text": str | None - The main text content of the page.
                   - "tables": List[str] | None - A list of HTML strings, each representing a table.
                   - "images_metadata": List[Dict[str, Any]] | None - List of image metadata dicts.
                   - "svg_graphics": List[str] | None - A list of SVG strings.
                   - "errors": List[str] | None - List of error messages for this page.
    Returns:
        str: An HTML string combining the page elements.
    """
    html_parts = []

    page_number = page_data.get("page_number", "N/A")
    html_parts.append(f"<h1>Page {page_number}</h1>")

    # 1. Display Page-Level Errors (if any)
    page_errors = page_data.get("errors", [])
    if page_errors:
        html_parts.append("<div style='border: 2px solid red; padding: 10px; margin-bottom: 15px;'>")
        html_parts.append("<h3>Processing Errors on this Page:</h3><ul>")
        for err in page_errors:
            html_parts.append(f"<li>{html.escape(err)}</li>")
        html_parts.append("</ul></div>")

    # 2. Add Main Text Content
    text_content = page_data.get("text") # Can be None if extraction failed or text is an error message itself
    html_parts.append("<div><h2>Extracted Text</h2>")
    if text_content and not any(err_msg in text_content for err_msg in (page_errors if page_errors else [])): # Avoid duplicating error
        escaped_text = html.escape(text_content)
        formatted_text = escaped_text.replace("\n\n", "<br><br>").replace("\n", "<br>")
        html_parts.append(f"<p>{formatted_text}</p>")
    elif text_content and "Error extracting text:" in text_content: # If text itself is an error message
        html_parts.append(f"<p style='color:red;'>{html.escape(text_content)}</p>")
    else: # No text or text extraction error already listed in page_errors
        html_parts.append("<p>No significant text extracted or an error occurred (see errors above if any).</p>")
    html_parts.append("</div>")
    

    # 3. Add Extracted Tables
    tables_html = page_data.get("tables")
    if tables_html: # tables_html is List[str]
        html_parts.append("<div><h2>Extracted Tables</h2>")
        for i, table_h in enumerate(tables_html):
            html_parts.append(f"<h4>Table {i+1}</h4>{table_h}") # table_h is already HTML
        html_parts.append("</div>")
    elif "Table extraction failed" in "".join(page_errors or []): # Check if error was due to tables
        html_parts.append("<div><h2>Extracted Tables</h2><p style='color:red;'>Table extraction failed (see errors above).</p></div>")


    # 4. Add Images and their OCRed Text
    images_metadata_list = page_data.get("images_metadata")
    if images_metadata_list: # images_metadata_list is List[Dict[str, Any]]
        html_parts.append("<div><h2>Extracted Images</h2>")
        for i, img_item in enumerate(images_metadata_list):
            # img_item could have "error" key from extract_images_from_page
            # or "metadata_error" from get_image_metadata_with_paddleocr
            
            img_id_text = f"Image {i+1}"
            if "xref" in img_item: img_id_text += f" (XRef: {img_item['xref']})"
            if "format" in img_item: img_id_text += f" (Format: {img_item['format']})"

            html_parts.append(f"<div><h4>{img_id_text}</h4>")
            
            if img_item.get("error"): # Error during image extraction itself
                html_parts.append(f"<p style='color:red;'>Error extracting this image: {html.escape(img_item['error'])}</p>")
            else:
                # Placeholder for the image itself
                html_parts.append(f"<div style='border:1px solid black; padding:10px; margin:5px; background-color:#f0f0f0;'>[Image Placeholder for {img_id_text}]</div>")
                
                ocr_text_display = "No OCR data."
                metadata_error = img_item.get("metadata_error") # Error from PaddleOCR step
                
                if metadata_error:
                    ocr_text_display = f"<span style='color:red;'>Could not get OCR metadata: {html.escape(metadata_error)}</span>"
                elif "metadata" in img_item and img_item["metadata"]:
                    ocr_text = img_item["metadata"].get("ocr_text", "")
                    if ocr_text.strip():
                        ocr_text_display = html.escape(ocr_text)
                    else:
                        ocr_text_display = "No significant OCR text extracted."
                
                html_parts.append(f"<div><h5>Image OCR Text:</h5><p>{ocr_text_display}</p></div>")
            html_parts.append("</div>")
        html_parts.append("</div>")
    elif "Image extraction failed" in "".join(page_errors or []):
         html_parts.append("<div><h2>Extracted Images</h2><p style='color:red;'>Image extraction failed (see errors above).</p></div>")


    # 5. Add SVG Graphics
    svg_graphics_list = page_data.get("svg_graphics")
    if svg_graphics_list: # svg_graphics_list is List[str]
        html_parts.append("<div><h2>Extracted SVG Graphics</h2>")
        for i, svg_content in enumerate(svg_graphics_list):
            escaped_svg_snippet = html.escape(svg_content[:250] + "..." if len(svg_content) > 250 else svg_content)
            html_parts.append(f"<div><h4>SVG Graphic {i+1}</h4><pre style='border:1px solid #ccc; padding:5px; max-height:150px; overflow:auto;'>{escaped_svg_snippet}</pre></div>")
        html_parts.append("</div>")
    elif "SVG extraction failed" in "".join(page_errors or []):
        html_parts.append("<div><h2>Extracted SVG Graphics</h2><p style='color:red;'>SVG extraction failed (see errors above).</p></div>")
        
    return "\n".join(html_parts)
