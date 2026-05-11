import asyncio
import inspect
import logging
import mimetypes
import os
import re
import shutil
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, Optional

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
# NOTE: app.include_router(router) is moved to the bottom AFTER route definitions.

logger = logging.getLogger(__name__)

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
REPORT_DIR = os.path.abspath("files/pain_001_output_reports")


def _safe_report_path(filename: str) -> tuple[str, str]:
    safe_name = os.path.basename(filename)
    file_path = (Path(REPORT_DIR) / safe_name).resolve()
    report_root = Path(REPORT_DIR).resolve()
    try:
        file_path.relative_to(report_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report filename.")
    return str(file_path), safe_name


@router.post("/validate")
async def validate_file(file: UploadFile = File(...)):
    try:
        unique_id = uuid.uuid4().hex
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".xml", ".csv"]:
            raise HTTPException(status_code=400, detail="Only XML or CSV files are supported.")

        file_path = os.path.join(UPLOAD_DIR, f"{unique_id}_{file.filename}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Get version
        if ext == ".csv":
            version = get_version_from_filename(file.filename) or prompt_for_version(file.filename)
            if not version:
                return JSONResponse(status_code=400, content={"error": "Could not determine version from filename."})
            from utils.file_validation_util import generate_xml_from_csv

            xml_path = generate_xml_from_csv(file_path, version)
            if not xml_path:
                return JSONResponse(status_code=500, content={"error": "Failed to generate XML from CSV."})
        else:
            version = get_version_from_xml(file_path) or prompt_for_version(file.filename)
            if not version:
                return JSONResponse(status_code=400, content={"error": "Could not determine version from XML."})
            xml_path = file_path

        # Run validation
        passed, errors, diffs, extra_info = validate_and_compare(xml_path, version)

        # Generate reports
        html_path = write_annotated_html(
            xml_path,
            errors,
            "See console summary",
            output_dir=REPORT_DIR,
        )
        csv_report_path = write_individual_report(
            os.path.basename(file.filename),
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("Validation failed.")
        raise HTTPException(status_code=500, detail="Validation failed.")


@router.get("/download/html/{filename}")
async def download_html(filename: str):
    file_path, safe_name = _safe_report_path(filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="HTML report not found.")
    return FileResponse(path=file_path, media_type="text/html", filename=safe_name)


@router.get("/download/csv/{filename}")
async def download_csv(filename: str):
    file_path, safe_name = _safe_report_path(filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="CSV report not found.")
    return FileResponse(path=file_path, media_type="text/csv", filename=safe_name)


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


# ==== ADAPTER: call FastAPI route function without HTTP ======================
# Put this at the END of file_validation.py (after your current code).
try:
    # FastAPI re-exports Starlette's UploadFile; we construct the underlying starlette class.
    from starlette.datastructures import UploadFile as StarletteUploadFile
except Exception as e:
    raise RuntimeError("Unable to import Starlette UploadFile. Check your FastAPI/Starlette installation.") from e

# If you have a specific route function name, set it here
# e.g., ROUTE_FUNC_NAME = "validate_pain001"
ROUTE_FUNC_NAME: Optional[str] = None  # leave None to auto-detect

# Candidate function names to look for if ROUTE_FUNC_NAME not set
_POSSIBLE_ROUTE_FUNCS = (
    "validate_pain001",
    "validate_file_route",
    "validate_xml_route",
    "validate",
)


def _find_route_func() -> Callable:
    """
    Find an existing FastAPI route handler in this module that we can call directly.
    It should accept a single parameter like `file: UploadFile` (or similar).
    """
    import sys

    mod = sys.modules[__name__]

    if ROUTE_FUNC_NAME:
        fn = getattr(mod, ROUTE_FUNC_NAME, None)
        if not callable(fn):
            raise RuntimeError(f"ROUTE_FUNC_NAME='{ROUTE_FUNC_NAME}' not found or not callable.")
        return fn

    for name in _POSSIBLE_ROUTE_FUNCS:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn

    # Fallback: pick the first function with 'validate' in its name
    for name, obj in vars(mod).items():
        if callable(obj) and "validate" in name.lower():
            return obj

    raise RuntimeError(
        "No validator route function found.\n"
        "Set ROUTE_FUNC_NAME near the adapter section to your route function name, "
        "or ensure your function name contains 'validate' (e.g., validate_pain001)."
    )


def _make_upload_file(contents: bytes, filename: str) -> StarletteUploadFile:
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        # Newer Starlette (no content_type argument)
        return StarletteUploadFile(filename=filename, file=BytesIO(contents))
    except TypeError:
        # Older versions still expect content_type
        return StarletteUploadFile(filename=filename, file=BytesIO(contents), content_type=ctype)


async def validate_via_route_async(contents: bytes, filename: str) -> Dict[str, Any]:
    """
    Async adapter for calling the FastAPI route function inside an async context (e.g., FastAPI request).
    If the route is async, await it directly; if it's sync, run it in a worker thread.
    """
    route_fn = _find_route_func()
    upload = _make_upload_file(contents, filename)
    if inspect.iscoroutinefunction(route_fn):
        return await route_fn(upload)  # type: ignore[arg-type]
    else:
        return await asyncio.to_thread(lambda: route_fn(upload))  # type: ignore[arg-type]


def validate_via_route(contents: bytes, filename: str) -> Dict[str, Any]:
    """
    Sync adapter for CLI usage. If the route is async, run it with asyncio.run()
    when no loop is running. If a loop is already running (e.g., inside FastAPI),
    instruct callers to use `await validate_via_route_async(...)` instead.
    """
    route_fn = _find_route_func()
    upload = _make_upload_file(contents, filename)
    if inspect.iscoroutinefunction(route_fn):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop -> safe to use asyncio.run
            return asyncio.run(route_fn(upload))  # type: ignore[arg-type]
        else:
            # We're already in an event loop (e.g., FastAPI). Use async variant.
            raise RuntimeError("validate_via_route called in async context. Use `await validate_via_route_async(...)`.")
    else:
        return route_fn(upload)  # type: ignore[arg-type]
