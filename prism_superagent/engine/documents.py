"""Local document parsing, comparison, table extraction and optional OCR."""

import base64
import csv
import difflib
import io
import importlib.util
import json
import re
import shutil
import threading
import xml.etree.ElementTree as ET
from xml.dom import minidom

from prism_superagent.engine.attachments import attached_documents, request_text
from prism_superagent.engine.tabular import attached_tables

_TABLE_BLOCK = re.compile(r"\[Table: ([^\]]+)\]\s*\n([\s\S]*?)(?=\n\[Table: |\Z)", re.IGNORECASE)
_OCR_LOCK = threading.RLock()
_OCR_ENGINE = None


def classify_document_request(content):
    if isinstance(content, list):
        instructions = " ".join(item.get("text", "") for item in content if isinstance(item, dict)
                                and item.get("type") == "text").lower()
    else:
        instructions = request_text(content).lower()
    docs = attached_documents(content)
    if not docs and not isinstance(content, list):
        return None
    if isinstance(content, list) and re.search(r"\b(ocr|extract text from (?:this|the) image)\b", instructions):
        images = _image_data(content)
        if images and ocr_available():
            return "ocr_images", {"images": images}
    if len(docs) >= 2 and re.search(r"\b(compare|comparison|diff|differences)\b", instructions):
        return "document_compare", {"documents": docs[:4]}
    tables = attached_tables(content) if isinstance(content, str) else []
    if isinstance(content, str) and not tables:
        tables = _document_tables(docs)
    if tables and re.search(r"\b(convert|export|turn)\b.*\b(csv|excel|spreadsheet)\b.*\bjson\b|"
                            r"\bjson\b.*\b(from|of)\b.*\b(csv|excel|spreadsheet)\b", instructions):
        return "csv_to_json", {"tables": tables}
    if tables and re.search(r"\b(extract|show|list|display)\b.*\b(tables?|rows?)\b", instructions):
        return "table_extract", {"tables": tables}
    if docs and re.search(r"\b(extract|show|read)\b.*\b(text|contents?)\b", instructions):
        return "document_extract", {"documents": docs[:4]}
    if docs and re.search(r"\b(format|pretty.?print|validate|parse|check)\b.*\bjson\b", instructions):
        document = next((item for item in docs if item["filename"].lower().endswith(".json")), None)
        if document:
            return "json_format", {"text": document["text"]}
    if docs and re.search(r"\b(format|pretty.?print|validate|parse|check)\b.*\bxml\b", instructions):
        document = next((item for item in docs if item["filename"].lower().endswith(".xml")), None)
        if document:
            return "xml_format", {"text": document["text"]}
    if docs and re.search(r"\b(extract|get|find|query)\b.*\b(json|json path|key)\b", instructions):
        document = next((item for item in docs if item["filename"].lower().endswith(".json")), None)
        path = re.search(r"\b(?:path|key|field)\s+([\w.\[\]-]+)", instructions)
        if document and path:
            return "json_query", {"text": document["text"], "path": path.group(1)}
    if docs and re.search(r"\bextract\b.*\btag\b", instructions):
        document = next((item for item in docs if item["filename"].lower().endswith(".xml")), None)
        tag = re.search(r"\btag\s+([\w:.-]+)", instructions)
        if document and tag:
            return "xml_query", {"text": document["text"], "tag": tag.group(1)}
    return None


def execute_document(operation, inputs):
    if operation == "document_extract":
        return {"text": "\n\n".join(
            f"### {doc['filename']}\n{doc['text']}" for doc in inputs["documents"])}
    if operation == "document_compare":
        left, right = inputs["documents"][:2]
        diff = list(difflib.unified_diff(
            left["text"].splitlines(), right["text"].splitlines(),
            fromfile=left["filename"], tofile=right["filename"], lineterm=""))
        return {"diff": "\n".join(diff[:500]), "changed_lines": sum(
            1 for line in diff if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))}
    if operation == "table_extract":
        tables = inputs["tables"]
        return {"tables": [{"file": table["filename"], "sheet": table["sheet"],
                             "headers": table["headers"], "rows": table["records"][:500]}
                            for table in tables]}
    if operation == "csv_to_json":
        return {"json": [{"sheet": table["sheet"], "rows": table["records"]}
                         for table in inputs["tables"]]}
    if operation == "json_format":
        value = json.loads(inputs["text"])
        return {"formatted": json.dumps(value, ensure_ascii=False, indent=2), "valid": True}
    if operation == "json_query":
        value = json.loads(inputs["text"])
        for part in re.findall(r"([^.\[\]]+)|\[(\d+)\]", inputs["path"]):
            key = part[1] if part[1] else part[0]
            value = value[int(key)] if isinstance(value, list) else value[key]
        return {"path": inputs["path"], "value": value}
    if operation == "xml_format":
        root = ET.fromstring(inputs["text"])
        return {"formatted": minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(),
                "valid": True}
    if operation == "xml_query":
        root = ET.fromstring(inputs["text"])
        matches = [element.text or "" for element in root.iter()
                   if element.tag.rsplit("}", 1)[-1] == inputs["tag"]]
        return {"tag": inputs["tag"], "matches": matches, "count": len(matches)}
    if operation == "ocr_images":
        return {"texts": [_ocr_data_url(url) for url in inputs["images"]]}
    raise ValueError(f"Unsupported document operation: {operation}")


def ocr_available():
    return (_module_available("PIL") and
            ((shutil.which("tesseract") is not None and _module_available("pytesseract")) or
             _module_available("rapidocr_onnxruntime")))


def _module_available(name):
    return importlib.util.find_spec(name) is not None


def _image_data(content):
    images = []
    for item in content:
        if not isinstance(item, dict):
            continue
        image = item.get("image_url", {})
        url = image.get("url") if isinstance(image, dict) else None
        if isinstance(url, str) and url.startswith("data:image/"):
            images.append(url)
    return images


def _document_tables(documents):
    tables = []
    for doc in documents:
        for name, content in _TABLE_BLOCK.findall(doc["text"]):
            rows = list(csv.reader(io.StringIO(content.strip())))
            if len(rows) < 2:
                continue
            headers = [cell.strip() for cell in rows[0]]
            records = [dict(zip(headers, [cell.strip() for cell in row])) for row in rows[1:]
                       if len(row) == len(headers)]
            if records:
                tables.append({"filename": doc["filename"], "sheet": name,
                               "headers": headers, "records": records,
                               "numeric_columns": []})
        if doc["filename"].lower().endswith(".pdf") and not tables:
            candidate_rows = []
            for line in doc["text"].splitlines():
                if "\t" not in line and not re.search(r"\s{2,}", line) and "|" not in line:
                    continue
                cells = [cell.strip() for cell in re.split(r"\t+|\s{2,}|\s*\|\s*", line.strip(" |"))]
                if len(cells) > 1:
                    candidate_rows.append(cells)
            if len(candidate_rows) >= 2:
                width = max(map(len, candidate_rows))
                normalized = [row + [""] * (width - len(row)) for row in candidate_rows]
                headers = normalized[0]
                records = [dict(zip(headers, row)) for row in normalized[1:]]
                tables.append({"filename": doc["filename"], "sheet": "Extracted table",
                               "headers": headers, "records": records, "numeric_columns": []})
    return tables


def _ocr_data_url(data_url):
    from PIL import Image, ImageOps

    header, encoded = data_url.split(",", 1)
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("OCR image exceeds the 15 MB limit.")
    image = Image.open(io.BytesIO(raw))
    if image.width * image.height > 40_000_000:
        raise ValueError("OCR image exceeds the 40 megapixel limit.")
    image = ImageOps.exif_transpose(image).convert("RGB")
    text = _ocr_image(image)
    return {"mime_type": header[5:].split(";", 1)[0], "text": text}


def ocr_pdf_bytes(raw, max_pages=20):
    if not ocr_available() or not _module_available("fitz"):
        return ""
    import fitz
    from PIL import Image

    document = fitz.open(stream=raw, filetype="pdf")
    results = []
    for index, page in enumerate(document):
        if index >= max_pages:
            results.append("[OCR stopped after 20 pages]")
            break
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
        results.append(f"[Page {index + 1}]\n{_ocr_image(image)}")
    document.close()
    return "\n\n".join(results)


def _ocr_image(image):
    global _OCR_ENGINE
    if shutil.which("tesseract") and _module_available("pytesseract"):
        import pytesseract
        return pytesseract.image_to_string(image, timeout=30).strip()
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    with _OCR_LOCK:
        if _OCR_ENGINE is None:
            _OCR_ENGINE = RapidOCR()
        engine = _OCR_ENGINE
    results, _elapsed = engine(np.asarray(image))
    return "\n".join(item[1] for item in (results or []))

