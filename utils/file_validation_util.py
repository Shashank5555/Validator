from __future__ import annotations

import csv
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from defusedxml import ElementTree as DefusedET

DEFAULT_VERSION = os.getenv("PAIN001_DEFAULT_VERSION", "pain.001.001.03")
REPORT_OUTPUT_DIR = os.path.abspath("files/pain_001_output_reports")


@dataclass
class ValidationResult:
    passed: bool
    errors: List[str]
    diffs: List[str]
    extra_info: Dict[str, object]


def validate_and_compare(xml_path: str, version: str) -> Tuple[bool, List[str], List[str], Dict[str, object]]:
    errors: List[str] = []
    diffs: List[str] = []
    extra_info: Dict[str, object] = {"info_messages": []}

    xml_text = _read_file(xml_path)
    if xml_text is None:
        errors.append("Line 1 - File not found or unreadable.")
        extra_info.update(_default_checks(False))
        return False, errors, diffs, extra_info

    root, parse_error = _safe_parse(xml_text)
    if parse_error:
        errors.append(parse_error)
        extra_info.update(_default_checks(False))
        return False, errors, diffs, extra_info

    extra_info.update(_build_checks(root, xml_text))
    errors.extend(_duplicate_errors(xml_text))

    passed = len(errors) == 0
    return passed, errors, diffs, extra_info


def write_annotated_html(xml_path: str, errors: List[str], summary: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"report_{uuid.uuid4().hex}.html"
    output_path = os.path.join(output_dir, filename)

    xml_text = _read_file(xml_path) or ""
    error_lines = _extract_error_lines(errors)
    lines = xml_text.splitlines()

    highlighted_lines = []
    for idx, line in enumerate(lines, start=1):
        escaped = _escape_html(line)
        if idx in error_lines:
            highlighted_lines.append(f"<span class=\"error-line\">{escaped}</span>")
        else:
            highlighted_lines.append(escaped)

    html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>Validation Report</title>
  <style>
    body { background: #0f1115; color: #e6e6e6; font-family: Arial, sans-serif; padding: 24px; }
    .summary { margin-bottom: 16px; font-size: 14px; color: #9aa4b2; }
    pre { background: #151922; padding: 16px; border-radius: 8px; overflow-x: auto; }
    .error-line { background: rgba(255, 99, 71, 0.25); display: block; padding: 2px 4px; border-radius: 4px; }
  </style>
</head>
<body>
  <div class=\"summary\">{summary}</div>
  <pre>{content}</pre>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html.format(summary=_escape_html(summary), content="\n".join(highlighted_lines)))

    return output_path


def write_individual_report(
    filename: str,
    version: str,
    file_type: str,
    passed: bool,
    errors: List[str],
    diffs: List[str],
) -> str:
    os.makedirs(REPORT_OUTPUT_DIR, exist_ok=True)
    report_name = f"validation_{uuid.uuid4().hex}.csv"
    report_path = os.path.join(REPORT_OUTPUT_DIR, report_name)

    with open(report_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Filename", "Version", "Type", "Status", "Error Count", "Errors"])
        writer.writerow(
            [
                filename,
                version,
                file_type,
                "PASSED" if passed else "FAILED",
                len(errors),
                " | ".join(errors) if errors else "",
            ]
        )

    return report_path


def get_version_from_filename(filename: str) -> Optional[str]:
    match = re.search(r"(pain\.001\.[\d.]+)", filename, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def get_version_from_xml(xml_path: str) -> Optional[str]:
    xml_text = _read_file(xml_path)
    if not xml_text:
        return None
    root, parse_error = _safe_parse(xml_text)
    if parse_error:
        return None
    match = re.search(r"pain\.001\.[\d.]+", root.tag)
    return match.group(0) if match else None


def prompt_for_version(filename: str) -> Optional[str]:
    return DEFAULT_VERSION


def generate_xml_from_csv(csv_path: str, version: str) -> Optional[str]:
    try:
        with open(csv_path, "r", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
    except OSError:
        return None

    xml_lines = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        f"<Document xmlns=\"urn:iso:std:iso:20022:tech:xsd:{version}\">",
    ]

    for row in rows:
        xml_lines.append("  <Row>")
        for value in row:
            xml_lines.append(f"    <Cell>{_escape_xml(value)}</Cell>")
        xml_lines.append("  </Row>")

    xml_lines.append("</Document>")

    output_path = os.path.splitext(csv_path)[0] + ".xml"
    try:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(xml_lines))
    except OSError:
        return None

    return output_path


def _read_file(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _safe_parse(xml_text: str):
    try:
        return DefusedET.fromstring(xml_text), None
    except DefusedET.ParseError as exc:
        line, _column = getattr(exc, "position", (1, 0))
        return None, f"Line {line} - Invalid XML content."


def _extract_error_lines(errors: List[str]) -> Set[int]:
    line_numbers = set()
    for err in errors:
        match = re.search(r"Line (\d+)", err)
        if match:
            line_numbers.add(int(match.group(1)))
    return line_numbers


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _default_checks(passed: bool) -> Dict[str, object]:
    return {
        "nboftxs_passed": passed,
        "ctrlsum_passed": passed,
        "purpose_code_passed": passed,
        "utf8_encoding_passed": passed,
        "currency_code_passed": passed,
        "duplicate_msgid_passed": passed,
        "iban_passed": passed,
        "mmbid_passed": passed,
        "country_code_passed": passed,
        "duplicate_e2e_passed": passed,
        "payment_date_results": {"passed": passed},
    }


def _build_checks(root, xml_text: str) -> Dict[str, object]:
    checks = _default_checks(True)
    checks["nboftxs_passed"] = _has_numeric(root, "NbOfTxs")
    checks["ctrlsum_passed"] = _has_numeric(root, "CtrlSum")
    checks["purpose_code_passed"] = _has_text(root, "Purp")
    checks["utf8_encoding_passed"] = _is_utf8(xml_text)
    checks["currency_code_passed"] = _has_text(root, "Ccy")
    checks["iban_passed"] = _iban_present(root)
    checks["mmbid_passed"] = _has_text(root, "MmbId")
    checks["country_code_passed"] = _country_code_present(root)
    checks["duplicate_msgid_passed"] = _no_duplicates(xml_text, "MsgId")
    checks["duplicate_e2e_passed"] = _no_duplicates(xml_text, "EndToEndId")
    checks["payment_date_results"] = _payment_date_results(root)
    return checks


def _has_numeric(root, tag: str) -> bool:
    element = root.find(f".//{{*}}{tag}")
    if element is None or element.text is None:
        return False
    try:
        float(element.text.strip())
        return True
    except ValueError:
        return False


def _has_text(root, tag: str) -> bool:
    element = root.find(f".//{{*}}{tag}")
    return bool(element is not None and element.text and element.text.strip())


def _iban_present(root) -> bool:
    element = root.find(".//{*}IBAN")
    if element is None or not element.text:
        return False
    return len(element.text.strip()) >= 15


def _country_code_present(root) -> bool:
    element = root.find(".//{*}Ctry")
    if element is None or not element.text:
        return False
    value = element.text.strip()
    return len(value) == 2 and value.isalpha()


def _payment_date_results(root) -> Dict[str, object]:
    element = root.find(".//{*}ReqdExctnDt") or root.find(".//{*}ReqdColltnDt")
    if element is None or not element.text:
        return {"passed": False, "details": "Missing required payment date."}
    value = element.text.strip()
    is_valid = bool(re.match(r"\d{4}-\d{2}-\d{2}", value))
    return {"passed": is_valid, "details": value}


def _is_utf8(xml_text: str) -> bool:
    try:
        xml_text.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _no_duplicates(xml_text: str, tag: str) -> bool:
    values = _collect_tag_values(xml_text, tag)
    return len(values) == len(set(values))


def _duplicate_errors(xml_text: str) -> List[str]:
    errors: List[str] = []
    errors.extend(_duplicate_tag_errors(xml_text, "MsgId", "Duplicate Message ID"))
    errors.extend(_duplicate_tag_errors(xml_text, "EndToEndId", "Duplicate EndToEndId"))
    return errors


def _duplicate_tag_errors(xml_text: str, tag: str, label: str) -> List[str]:
    errors: List[str] = []
    seen: Dict[str, int] = {}
    pattern = re.compile(rf"<(?:(?:\w+):)?{tag}[^>]*>(.*?)</(?:(?:\w+):)?{tag}>")

    for line_no, line in enumerate(xml_text.splitlines(), start=1):
        match = pattern.search(line)
        if not match:
            continue
        value = match.group(1).strip()
        if value in seen:
            errors.append(f"Line {line_no} - {label}. Found: {value}")
        else:
            seen[value] = line_no

    return errors


def _collect_tag_values(xml_text: str, tag: str) -> List[str]:
    values = []
    pattern = re.compile(rf"<(?:(?:\w+):)?{tag}[^>]*>(.*?)</(?:(?:\w+):)?{tag}>")
    for line in xml_text.splitlines():
        match = pattern.search(line)
        if match:
            values.append(match.group(1).strip())
    return values
