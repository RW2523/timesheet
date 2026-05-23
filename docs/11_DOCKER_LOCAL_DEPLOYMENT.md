# Ajace TimeSheet AI Bot — Docker Local Deployment

The application should run fully local using Docker Compose.

## 1. Services

Required services:

```text
frontend
backend
worker
postgres
redis
```

Optional later:

```text
minio
nginx
trt-llm
ocr-worker
```

---

## 2. Docker Compose Skeleton

```yaml
version: "3.9"

services:
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
    depends_on:
      - backend

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./storage:/storage
    depends_on:
      - postgres
      - redis
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  worker:
    build: ./backend
    env_file:
      - .env
    volumes:
      - ./storage:/storage
    depends_on:
      - postgres
      - redis
    command: celery -A app.workers.celery_app worker --loglevel=info

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: timesheet_ai
      POSTGRES_USER: timesheet_user
      POSTGRES_PASSWORD: timesheet_pass
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

---

## 3. Environment Variables

Create `.env`:

```env
DATABASE_URL=postgresql+psycopg://timesheet_user:timesheet_pass@postgres:5432/timesheet_ai
REDIS_URL=redis://redis:6379/0
STORAGE_ROOT=/storage
MAX_UPLOAD_MB=2000
MAX_EXTRACTED_MB=5000
LLM_ENABLED=false
LLM_BASE_URL=http://host.docker.internal:9000
PRIMARY_LLM_MODEL=nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4
OCR_ENABLED=true
TESSERACT_ENABLED=true
```

---

## 4. Local Folder Structure

```text
project-root/
  docker-compose.yml
  .env
  frontend/
  backend/
  storage/
    uploads/
    extracted/
    raw_extractions/
    reports/
```

---

## 5. Backend Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 6. Backend Requirements

```text
fastapi
uvicorn[standard]
pydantic
pydantic-settings
sqlalchemy
sqlmodel
psycopg[binary]
alembic
celery
redis
python-multipart
pandas
openpyxl
python-docx
pymupdf
pdfplumber
pillow
rapidfuzz
python-dateutil
xlsxwriter
```

Optional OCR/AI:

```text
paddleocr
paddlepaddle
pytesseract
docling
httpx
```

---

## 7. Frontend Dockerfile

```dockerfile
FROM node:20-alpine

WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]
```

---

## 8. DGX Spark LLM Serving

For MVP, keep LLM optional behind an interface.

The app should work with:

```env
LLM_ENABLED=false
```

Then enable LLM when TensorRT-LLM service is ready.

LLM service interface:

```python
class LLMService:
    def extract_timesheet_json(self, file_metadata: dict, raw_content: str) -> dict:
        pass
```

---

## 9. Why No Kubernetes Yet

Kubernetes is not required for local DGX Spark MVP.

Use Docker Compose until:

- Multiple DGX/dev machines are needed.
- Production deployment is needed.
- Horizontal scaling is needed.
- Team CI/CD requires cluster rollout.
