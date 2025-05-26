# 1. Base Image
FROM python:3.10-slim-bookworm

# 2. Environment Variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# For PaddleOCR model storage (ensures it's in a known location if not default)
# However, PaddleOCR usually defaults to ~/.paddleocr/ which becomes /root/.paddleocr/
# ENV PADDLE_ extrêmement_DIR=/opt/paddleocr_models 
# (Above is an example; default /root/.paddleocr/ is usually fine and simpler)

# 3. System Dependencies Installation
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Tesseract OCR
    tesseract-ocr \
    tesseract-ocr-eng \
    # Ghostscript (for Camelot and PyMuPDF if it uses it for certain operations)
    ghostscript \
    # OpenCV headless dependencies (libgl1 is common, libglib2.0-0 also)
    libgl1-mesa-glx \
    # Tkinter (for Camelot, even if headless, sometimes needed for full feature set)
    tk-dev \
    # Git (good practice for some pip installs or future needs)
    git \
    # General utilities
    curl \
    # Clean up apt cache
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 4. PaddleOCR Model Handling
# Create a directory for models if a custom one were used (not strictly needed for default path)
# RUN mkdir -p /opt/paddleocr_models 
# Create a temporary script to download models
RUN echo "from paddleocr import PaddleOCR; print('Downloading PaddleOCR models...'); PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False, show_log=True); print('PaddleOCR models downloaded.')" > /tmp/download_paddle_models.py
# Run the script to download models. This will place them in /root/.paddleocr/
# Ensure this runs as root (default) so models are in a known system location.
RUN python /tmp/download_paddle_models.py \
    && rm /tmp/download_paddle_models.py
# The models will be in /root/.paddleocr/ and included in the image.

# 5. Tesseract Language Data (already installed tesseract-ocr-eng)

# 6. Application Code
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt requirements.txt

# Install Python dependencies
# Using --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
# This assumes the Dockerfile is in the root of pdf_parser_py_lib
# and the app code (pdf_parser module, static, templates, etc.) is in this directory.
COPY . .
# If your project structure was:
# pdf_parser_py_lib/
#   ├── Dockerfile
#   ├── pdf_parser/
#   ├── static/
#   └── templates/
#   └── requirements.txt
# Then `COPY . .` is correct.

# Ensure the job storage directory exists and is writable (though it's created by main.py too)
# This directory will be inside the container's /app directory.
RUN mkdir -p pdf_job_storage

# 7. Port Exposure
EXPOSE 8000

# 8. Command
# Assumes main.py is inside a 'pdf_parser' package directory (e.g., /app/pdf_parser/main.py)
# The module path for uvicorn is then 'pdf_parser.main:app'
CMD ["uvicorn", "pdf_parser.main:app", "--host", "0.0.0.0", "--port", "8000"]
