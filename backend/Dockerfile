# Container image for the CCA Quiz (FastAPI). Referenced by the bundle README.
FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Runtime data dirs (also mountable as volumes)
RUN mkdir -p quiz_results certificates outbox

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
