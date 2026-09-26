FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
# Korean fonts for charts/PDF export; Tesseract (eng+kor) enables OCR of scanned PDFs and images.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-nanum tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY tests ./tests

RUN useradd -m office && mkdir -p /app/data && chown -R office /app
USER office
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
