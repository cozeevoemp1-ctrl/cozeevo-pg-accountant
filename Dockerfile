FROM python:3.11-slim

WORKDIR /app

# System dependencies for PDF parsing
RUN apt-get update && apt-get install -y \
    libpoppler-cpp-dev \
    poppler-utils \
    ghostscript \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create necessary directories
RUN mkdir -p data/raw data/processed data/exports dashboards workflows/n8n

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
