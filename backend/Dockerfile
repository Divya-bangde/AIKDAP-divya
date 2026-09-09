FROM python:3.12-slim

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1

# Prevent Python output buffering
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# OCR engine (Sprint 12.5). tesseract-ocr pulls in libtesseract5 and
# English language data (tesseract-ocr-eng) automatically; ~19MB total.
# Additional languages need their own tesseract-ocr-<lang> package --
# not installed speculatively since nothing in this deployment needs
# one yet.
RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

EXPOSE 8000

# Shell form so ${PORT} expands: managed hosts (Render, Fly) assign the
# port at runtime and route to it. Defaults to 8000 when unset, which is
# what docker-compose and the EXPOSE above expect locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]