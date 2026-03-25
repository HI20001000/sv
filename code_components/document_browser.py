from __future__ import annotations

from pathlib import Path
from typing import List
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


INPUT_DIR = Path("input_documents")
SUPPORTED_EXTENSIONS = {".txt", ".docx"}
DOCX_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TEXT_ENCODINGS = ["utf-8-sig", "utf-8", "cp950", "big5", "gbk", "latin-1"]


def list_input_documents() -> List[Path]:
    if not INPUT_DIR.exists():
        return []
    files = [
        path
        for path in INPUT_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.name.lower())


def load_document_content(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".txt":
        return _read_text_file(path)
    if ext == ".docx":
        return _read_docx_file(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def _read_text_file(path: Path) -> str:
    for encoding in TEXT_ENCODINGS:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_docx_file(path: Path) -> str:
    try:
        with ZipFile(path) as zf:
            xml_bytes = zf.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("Invalid DOCX: missing word/document.xml") from exc
    except BadZipFile as exc:
        raise ValueError("Invalid DOCX: not a zip archive") from exc

    root = ET.fromstring(xml_bytes)
    paragraphs = []
    for paragraph in root.findall(".//w:p", DOCX_NAMESPACE):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", DOCX_NAMESPACE)]
        merged = "".join(texts).strip()
        if merged:
            paragraphs.append(merged)
    return "\n".join(paragraphs)
