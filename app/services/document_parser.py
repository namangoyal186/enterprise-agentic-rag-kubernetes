import csv
import io
import json
import os
import logfire

from app.ingestion.chunking.splitter import chunk_text
from app.ingestion.loaders.pdf import parse_pdf
from app.ingestion.loaders.text import parse_text


def parse_csv_content(content: str) -> str:
    """Parse CSV text into semantic line-by-line passage blocks."""
    lines = []
    f = io.StringIO(content)
    reader = csv.reader(f)
    headers = []
    for i, row in enumerate(reader):
        if not row:
            continue
        if i == 0:
            headers = [h.strip() for h in row]
            continue
        row_parts = []
        for j, val in enumerate(row):
            header = headers[j] if j < len(headers) else f"Col{j+1}"
            row_parts.append(f"{header}: {val.strip()}")
        lines.append(f"Row {i}: " + " | ".join(row_parts))
    return "\n".join(lines)


def extract_document_text(file_path: str, filename: str) -> str:
    """Extract raw text from a document based on its extension."""
    ext = os.path.splitext(filename)[1].lower()
    with logfire.span("Extract Document Text", filename=filename, extension=ext):
        if ext == ".pdf":
            return parse_pdf(file_path)
        elif ext in [".txt", ".md"]:
            return parse_text(file_path)
        elif ext in [".yaml", ".yml", ".json"]:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            # If JSON, format nicely
            if ext == ".json":
                try:
                    parsed = json.loads(content)
                    return json.dumps(parsed, indent=2)
                except Exception:
                    pass
            return content
        elif ext == ".csv":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return parse_csv_content(content)
        else:
            raise ValueError(f"Unsupported file format: {ext}. Supported: PDF, YAML, JSON, TXT, MD, CSV.")


def process_uploaded_document(file_path: str, filename: str, chunk_size: int = 1200) -> list[str]:
    """
    Extracts text and splits into chunks ready for embedding.
    Returns list of chunk text strings.
    """
    text = extract_document_text(file_path, filename)
    if not text or not text.strip():
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".pdf":
            raise ValueError(
                f"Could not extract digital text from '{filename}'. This PDF appears to be a scanned image or photo without selectable text. Please upload text-based PDFs, YAML/JSON configs, CSV, or Markdown files."
            )
        raise ValueError(f"File '{filename}' is empty or contains no readable text.")
    chunks = chunk_text(text, chunk_size=chunk_size)
    if not chunks:
        raise ValueError(f"No chunks could be generated from '{filename}'.")
    return chunks

