FROM python:3.11-slim

WORKDIR /app

# System dependencies for OCR, document parsing, and Docling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    ghostscript \
    libpq-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch FIRST so Docling doesn't pull CUDA variant
RUN pip install --no-cache-dir \
    torch==2.5.1 \
    torchvision==0.20.1 \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    # Re-pin torch/torchvision (surya-ocr may pull a newer one)
    pip install --no-cache-dir --no-deps \
        "torch==2.5.1" \
        "torchvision==0.20.1" \
        --index-url https://download.pytorch.org/whl/cpu

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
