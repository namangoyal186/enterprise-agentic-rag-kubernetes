import os
import tempfile
import pytest

from app.services.document_parser import (
    extract_document_text,
    parse_csv_content,
    process_uploaded_document,
)


def test_csv_parser():
    raw_csv = "Name,Role,Port\nIngress,Controller,80\nCoreDNS,DNS,53\n"
    parsed = parse_csv_content(raw_csv)
    assert "Row 1: Name: Ingress | Role: Controller | Port: 80" in parsed
    assert "Row 2: Name: CoreDNS | Role: DNS | Port: 53" in parsed


def test_yaml_and_text_processing():
    sample_yaml = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
spec:
  replicas: 3
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(sample_yaml)
        tmp_path = f.name

    try:
        chunks = process_uploaded_document(tmp_path, "deployment.yaml")
        assert len(chunks) > 0
        assert "nginx-deployment" in chunks[0]
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_unsupported_format():
    with pytest.raises(ValueError) as exc:
        extract_document_text("dummy.exe", "dummy.exe")
    assert "Unsupported file format" in str(exc.value)
