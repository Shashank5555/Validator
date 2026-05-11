import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from utils.file_validation_util import (
    get_version_from_filename,
    get_version_from_xml,
    prompt_for_version,
    validate_and_compare,
    write_annotated_html,
    write_individual_report,
)

router = APIRouter(prefix="/files", tags=["Files"])
app = FastAPI(title="Validator")

UPLOAD_DIR = "temp_uploads"
REPORT_DIR = "files/pain_001_output_reports"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)
REPORT_ROOT = Path(REPORT_DIR).resolve()


def _sanitize_upload_name(filename: str, fallback: str) -> str:
    safe_name = os.path.basename(filename or "").strip() or fallback
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", safe_name).lstrip(".")
    if not safe_name or not re.search(r"[A-Za-z0-9]", safe_name):
        return fallback
    return safe_name


def _resolve_report_path(filename: str, label: str) -> Path:
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        raise HTTPException(status_code=400, detail=f"Invalid {label} report filename.")
    report_path = (REPORT_ROOT / safe_name).resolve()
    if not report_path.is_relative_to(REPORT_ROOT):
        raise HTTPException(status_code=400, detail=f"Invalid {label} report filename.")
    return report_path


@router.post("/validate")
async def validate_file(file: UploadFile = File(...)):
    unique_id = uuid.uuid4().hex
    safe_filename = _sanitize_upload_name(file.filename, "upload.xml")
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in [".xml", ".csv"]:
        raise HTTPException(status_code=400, detail="Only XML or CSV files are supported.")

    file_path = os.path.join(UPLOAD_DIR, f"{unique_id}_{safe_filename}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Get version
    if ext == ".csv":
        version = get_version_from_filename(safe_filename) or prompt_for_version(safe_filename)
        if not version:
            return JSONResponse(status_code=400, content={"error": "Could not determine version from filename."})
        from utils.file_validation_util import generate_xml_from_csv

        xml_path = generate_xml_from_csv(file_path, version)
        if not xml_path:
            return JSONResponse(status_code=500, content={"error": "Failed to generate XML from CSV."})
    else:
        version = get_version_from_xml(file_path) or prompt_for_version(safe_filename)
        if not version:
            return JSONResponse(status_code=400, content={"error": "Could not determine version from XML."})
        xml_path = file_path

    # Run validation
    passed, errors, diffs, extra_info = validate_and_compare(xml_path, version)

    # Generate reports
    html_path = write_annotated_html(xml_path, errors, "See console summary", output_dir=REPORT_DIR)
    csv_report_path = write_individual_report(
        safe_filename,
        version,
        "CSV" if ext == ".csv" else "XML",
        passed,
        errors,
        diffs,
    )

    # Build response
    return {
        "status": "PASSED" if passed else "FAILED",
        "filename": file.filename,
        "version": version,
        "errors": parse_structured_errors(errors),
        "info_messages": extra_info.get("info_messages", []),
        "checks": {
            "NbOfTxs": extra_info.get("nboftxs_passed"),
            "CtrlSum": extra_info.get("ctrlsum_passed"),
            "Purpose Code": extra_info.get("purpose_code_passed"),
            "UTF-8 Encoding": extra_info.get("utf8_encoding_passed"),
            "Currency Code": extra_info.get("currency_code_passed"),
            "Duplicate Message ID": extra_info.get("duplicate_msgid_passed"),
            "IBAN checksum": extra_info.get("iban_passed"),
            "MmbId": extra_info.get("mmbid_passed"),
            "Country Code": extra_info.get("country_code_passed"),
            "Duplicate EndToEndId": extra_info.get("duplicate_e2e_passed"),
            "Payment Dates": extra_info.get("payment_date_results", {}),
        },
        "html_report_url": f"/files/download/html/{os.path.basename(html_path)}",
        "csv_report_url": f"/files/download/csv/{os.path.basename(csv_report_path)}",
    }


@router.get("/download/html/{filename}")
async def download_html(filename: str):
    report_path = _resolve_report_path(filename, "HTML")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="HTML report not found.")
    return FileResponse(path=report_path, media_type="text/html", filename=report_path.name)


@router.get("/download/csv/{filename}")
async def download_csv(filename: str):
    report_path = _resolve_report_path(filename, "CSV")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="CSV report not found.")
    return FileResponse(path=report_path, media_type="text/csv", filename=report_path.name)


def parse_structured_errors(errors: list):
    line_errors = []
    additional_error_details = []

    for err in errors:
        match = re.search(r"Line (\d+)\s*-\s*(.*)", err)
        if match:
            line_no = int(match.group(1))
            message = match.group(2).strip()
            # Attempt to extract a value (like a duplicate ID or date) after "Found:"
            found_match = re.search(r"Found: ([^.\n]*)", message)
            found_value = found_match.group(1).strip() if found_match else None

            line_errors.append(
                {
                    "line_no": line_no,
                    "line_name": f"Line {line_no}",
                    "message": message,
                    "found": found_value,
                }
            )
        else:
            additional_error_details.append(err.strip())
    return {"line_errors": line_errors, "additional_error_details": additional_error_details}


# Include router AFTER all routes have been added
app.include_router(router)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(index_path)
