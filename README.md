# Validator

A dark-themed pain.001 XML editor and validator with a FastAPI backend and a single-container Docker setup.

## Project Structure

- `file_validation.py` – FastAPI backend and API routes
- `static/` – Frontend assets (HTML/CSS/JS)
- `utils/` – Validation helpers and report generators
- `files/pain_001_output_reports/` – Generated HTML/CSV reports
- `temp_uploads/` – Temporary upload storage
- `Dockerfile` / `docker-compose.yml` – Container configuration

## Build and Run (Docker)

```bash
docker compose up --build
```

Open the app at: `http://localhost:8000`

## Run Locally (Python)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn file_validation:app --reload --host 0.0.0.0 --port 8000
```

Open the app at: `http://localhost:8000`
