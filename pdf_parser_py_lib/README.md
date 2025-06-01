# PDF Parser Application

This project is a PDF processing application built with FastAPI. It provides an API to upload PDF files, extract text, tables, images, and SVG graphics from them, and view the extracted content page by page.

## Features

- PDF Upload and Background Processing
- Text Extraction
- Table Extraction
- Image Extraction (with OCR if PaddleOCR is available)
- SVG Graphics Extraction
- Page-by-page viewing of extracted content (HTML and Raw Data)
- API for status tracking and results retrieval

## API Documentation

This application uses FastAPI, which automatically generates interactive API documentation.
Once the application is running (e.g., locally using Uvicorn), you can access the documentation at the following URLs:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

These interfaces allow you to explore the available API endpoints, their parameters, and test them directly in your browser.

## Running the Application

(Instructions on how to run the application, configure dependencies, etc., would typically go here. For example:)

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
2.  Run the FastAPI application using Uvicorn:
    ```bash
    cd pdf_parser_py_lib
    python -m uvicorn pdf_parser.main:app --reload --port 8000 --host 0.0.0.0
    ```

Refer to the Uvicorn and FastAPI documentation for more deployment options.
