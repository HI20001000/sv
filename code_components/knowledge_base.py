from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from code_components.document_browser import SUPPORTED_EXTENSIONS, load_document_content
from code_components.langChain import extract_kb_script_features_with_prompt, make_llm
from code_components.prompt_registry import KB_FEATURE_PROMPT_PATH, resolve_prompt_path
from code_components.story_schema import empty_story_schema, normalize_story_schema


PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_BASE_ROOT = PROJECT_ROOT / "knowledge_base"
RAW_SCRIPTS_ROOT = KNOWLEDGE_BASE_ROOT / "raw_scripts"
STRUCTURED_SCRIPTS_ROOT = KNOWLEDGE_BASE_ROOT / "structured_scripts"
INDEX_PATH = KNOWLEDGE_BASE_ROOT / "index.json"
DEFAULT_KB_FEATURE_CHUNK_SIZE = 4000
DEFAULT_KB_FEATURE_MAX_WORKERS = 10

ProgressCallback = Callable[[str, dict[str, Any]], None]
_INDEX_LOCK = threading.Lock()


def ensure_knowledge_base() -> None:
    RAW_SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
    STRUCTURED_SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)
    if not INDEX_PATH.exists():
        INDEX_PATH.write_text(json.dumps({"items": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def create_knowledge_record(
    filename: str,
    content: bytes,
    overwrite_record_id: str | None = None,
) -> dict[str, Any]:
    ensure_knowledge_base()
    original_name = Path(filename or "").name
    if not original_name:
        raise ValueError("Filename is required.")
    if Path(original_name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Only .txt and .docx files are supported.")

    storage_name = _safe_storage_filename(original_name)
    if overwrite_record_id:
        existing = get_knowledge_record(overwrite_record_id)
        if str(existing.get("original_filename") or "").casefold() != original_name.casefold():
            raise ValueError("Overwrite target filename does not match the uploaded filename.")
        if str(existing.get("status") or "").lower() == "processing":
            raise ValueError("This knowledge record is still processing. Please wait before overwriting it.")
        record_id = str(existing["id"])
    else:
        conflicts = find_knowledge_records_by_filename(original_name)
        if conflicts:
            raise FileExistsError(f"Knowledge record already exists for filename: {original_name}")
        existing = {}
        record_id = _build_record_id(original_name)

    raw_dir = RAW_SCRIPTS_ROOT / record_id
    structured_dir = STRUCTURED_SCRIPTS_ROOT / record_id
    raw_dir.mkdir(parents=True, exist_ok=bool(overwrite_record_id))
    structured_dir.mkdir(parents=True, exist_ok=True)

    if overwrite_record_id:
        _clear_record_directory(raw_dir, RAW_SCRIPTS_ROOT)
        _clear_record_directory(structured_dir, STRUCTURED_SCRIPTS_ROOT)

    raw_path = raw_dir / storage_name
    raw_path.write_bytes(content)

    now = _now()
    record = {
        "id": record_id,
        "original_filename": original_name,
        "raw_path": _relative_path(raw_path),
        "structured_path": "",
        "status": "uploaded",
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "size": raw_path.stat().st_size,
        "source_chars": 0,
        "prompt_file": _relative_path(resolve_prompt_path(KB_FEATURE_PROMPT_PATH)),
        "error": None,
    }
    _upsert_record(record)
    return dict(record)


def find_knowledge_records_by_filename(filename: str) -> list[dict[str, Any]]:
    ensure_knowledge_base()
    original_name = Path(filename or "").name
    if not original_name:
        return []
    target_name = original_name.casefold()
    return [
        item
        for item in list_knowledge_records()
        if str(item.get("original_filename") or "").casefold() == target_name
    ]


def list_knowledge_records() -> list[dict[str, Any]]:
    with _INDEX_LOCK:
        index = _read_index_unlocked()

    items = [dict(item) for item in index.get("items", []) if isinstance(item, dict)]
    items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
    return items


def get_knowledge_record(record_id: str) -> dict[str, Any]:
    safe_id = _safe_record_id(record_id)
    with _INDEX_LOCK:
        index = _read_index_unlocked()

    for item in index.get("items", []):
        if isinstance(item, dict) and item.get("id") == safe_id:
            return dict(item)
    raise FileNotFoundError(f"Knowledge record not found: {safe_id}")


def get_knowledge_item(record_id: str) -> dict[str, Any]:
    record = get_knowledge_record(record_id)
    features: dict[str, Any] | None = None
    structured_path = str(record.get("structured_path") or "")
    if structured_path:
        resolved_path = _resolve_relative_path(structured_path)
        if resolved_path.exists():
            features = json.loads(resolved_path.read_text(encoding="utf-8-sig"))

    return {
        "record": record,
        "features": _normalize_kb_feature_schema(features or {}),
    }


def mark_knowledge_record_failed(record_id: str, error: str) -> dict[str, Any]:
    return update_knowledge_record(record_id, status="failed", error=error)


def update_knowledge_record(record_id: str, **updates: Any) -> dict[str, Any]:
    safe_id = _safe_record_id(record_id)
    with _INDEX_LOCK:
        index = _read_index_unlocked()
        items = index.setdefault("items", [])
        for position, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") == safe_id:
                updated = {
                    **item,
                    **updates,
                    "updated_at": _now(),
                }
                items[position] = updated
                _write_index_unlocked(index)
                return dict(updated)
    raise FileNotFoundError(f"Knowledge record not found: {safe_id}")


def process_knowledge_record_features(
    llm,
    record_id: str,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    record = update_knowledge_record(record_id, status="processing", error=None)
    raw_path = _resolve_relative_path(str(record.get("raw_path") or ""))

    try:
        _emit_progress(progress_callback, "reading", f"Reading source text: {record['original_filename']}")
        raw_script = load_document_content(raw_path)
        source_chars = len(raw_script)
        record = update_knowledge_record(record_id, source_chars=source_chars)

        features = _extract_features_with_chunking(
            llm=llm,
            raw_script=raw_script,
            record=record,
            progress_callback=progress_callback,
        )
        features = _with_task_metadata(features, record=record, source_chars=source_chars)

        _emit_progress(progress_callback, "writing", "Writing structured features and updating index")
        structured_dir = STRUCTURED_SCRIPTS_ROOT / record["id"]
        structured_dir.mkdir(parents=True, exist_ok=True)
        structured_path = structured_dir / "features.json"
        structured_path.write_text(json.dumps(features, ensure_ascii=False, indent=2), encoding="utf-8")

        record = update_knowledge_record(
            record_id,
            status="completed",
            structured_path=_relative_path(structured_path),
            source_chars=source_chars,
            prompt_file=_relative_path(resolve_prompt_path(KB_FEATURE_PROMPT_PATH)),
            error=None,
        )
        _emit_progress(progress_callback, "completed", "Knowledge extraction completed")
        return {
            "record": record,
            "features": features,
        }
    except Exception as exc:
        error_message = str(exc)
        mark_knowledge_record_failed(record_id, error_message)
        _emit_progress(progress_callback, "failed", f"Knowledge extraction failed: {error_message}")
        raise


def _extract_features_with_chunking(
    llm,
    raw_script: str,
    record: dict[str, Any],
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    text = raw_script.strip()
    if not text:
        _emit_progress(progress_callback, "extracting", "Source text is empty; writing empty schema")
        return _empty_kb_feature_schema()

    chunk_size = _read_kb_feature_chunk_size_config()
    chunks = _split_text(text, chunk_size)
    if len(chunks) <= 1:
        _emit_progress(progress_callback, "extracting", f"AI extraction started (chars: {len(text)})")
        raw_response = extract_kb_script_features_with_prompt(
            llm=llm,
            script_text=text,
            task_mode="direct_extract",
            source_file_name=str(record.get("original_filename") or ""),
            record_id=str(record.get("id") or ""),
            chunk_index=1,
            chunk_count=1,
            prompt_path=KB_FEATURE_PROMPT_PATH,
        )
        return _normalize_kb_feature_schema(_parse_json_response(raw_response, "Knowledge feature extraction"))

    max_workers = min(_read_kb_feature_max_workers_config(), len(chunks))
    partials_by_index: list[dict[str, Any] | None] = [None] * len(chunks)
    completed_count = 0
    _emit_progress(
        progress_callback,
        "extracting",
        f"AI chunk extraction started ({len(chunks)} chunks, threshold: {chunk_size}, concurrency: {max_workers})",
    )

    llm_thread_local = threading.local()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _extract_single_kb_chunk,
                llm=llm,
                llm_thread_local=llm_thread_local,
                chunk=chunk,
                record=record,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
            ): chunk_index
            for chunk_index, chunk in enumerate(chunks, start=1)
        }

        for future in as_completed(futures):
            chunk_index = futures[future]
            try:
                partials_by_index[chunk_index - 1] = future.result()
            except Exception as exc:
                _emit_progress(progress_callback, "extracting", f"Chunk {chunk_index}/{len(chunks)} skipped: {exc}")
            completed_count += 1
            _emit_progress(
                progress_callback,
                "extracting",
                f"Chunk extraction completed {completed_count}/{len(chunks)} (last: {chunk_index})",
            )

    partials = [item for item in partials_by_index if item is not None]

    if not partials:
        raise ValueError("Knowledge feature extraction failed for all chunks.")

    _emit_progress(progress_callback, "merging", f"Merging {len(partials)} extracted chunks")
    raw_response = extract_kb_script_features_with_prompt(
        llm=llm,
        script_text="",
        task_mode="merge_chunks",
        partial_results_json=json.dumps(partials, ensure_ascii=False, indent=2),
        source_file_name=str(record.get("original_filename") or ""),
        record_id=str(record.get("id") or ""),
        chunk_index="",
        chunk_count=len(chunks),
        prompt_path=KB_FEATURE_PROMPT_PATH,
    )
    return _normalize_kb_feature_schema(_parse_json_response(raw_response, "Knowledge chunk merge"))


def _extract_single_kb_chunk(
    llm,
    llm_thread_local: threading.local | None,
    chunk: str,
    record: dict[str, Any],
    chunk_index: int,
    chunk_count: int,
) -> dict[str, Any]:
    worker_llm = _get_parallel_worker_llm(llm=llm, llm_thread_local=llm_thread_local)
    raw_response = extract_kb_script_features_with_prompt(
        llm=worker_llm,
        script_text=chunk,
        task_mode="chunk_extract",
        source_file_name=str(record.get("original_filename") or ""),
        record_id=str(record.get("id") or ""),
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        prompt_path=KB_FEATURE_PROMPT_PATH,
    )
    return _normalize_kb_feature_schema(
        _parse_json_response(raw_response, f"Knowledge chunk extraction {chunk_index}")
    )


def _get_parallel_worker_llm(llm, llm_thread_local: threading.local | None):
    if llm_thread_local is None:
        return llm

    worker_llm = getattr(llm_thread_local, "llm", None)
    if worker_llm is None:
        worker_llm = make_llm()
        llm_thread_local.llm = worker_llm
    return worker_llm


def _with_task_metadata(
    features: dict[str, Any],
    record: dict[str, Any],
    source_chars: int,
) -> dict[str, Any]:
    normalized = _normalize_kb_feature_schema(features)
    metadata = normalized.get("task_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["task_id"] = str(metadata.get("task_id") or record.get("id", ""))
    metadata["source_type"] = str(metadata.get("source_type") or "knowledge_base_upload")
    metadata["source_title"] = str(metadata.get("source_title") or record.get("original_filename", ""))
    metadata["analysis_purpose"] = str(metadata.get("analysis_purpose") or "knowledge_base_feature_extraction")
    metadata["version"] = str(metadata.get("version") or "1.0")
    metadata["notes"] = str(
        metadata.get("notes")
        or f"source_chars={source_chars}; prompt_file={record.get('prompt_file', '')}; extracted_at={_now()}"
    )
    normalized["task_metadata"] = metadata
    return normalized


def _normalize_kb_feature_schema(data: Any) -> dict[str, Any]:
    return normalize_story_schema(data)


def _empty_kb_feature_schema() -> dict[str, Any]:
    return empty_story_schema()


def _parse_json_response(raw_response: str, source_name: str = "LLM") -> Any:
    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError(f"{source_name} returned non-JSON content")


def _split_text(text: str, chunk_size: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", normalized) if p.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_split_long_block(paragraph, chunk_size))
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            chunks.append(current.strip())
            current = paragraph

    if current.strip():
        chunks.append(current.strip())
    return chunks


def _split_long_block(block: str, chunk_size: int) -> list[str]:
    return [
        block[index : index + chunk_size].strip()
        for index in range(0, len(block), chunk_size)
        if block[index : index + chunk_size].strip()
    ]


def _read_kb_feature_chunk_size_config() -> int:
    raw_size = os.getenv("KB_FEATURE_CHUNK_SIZE") or os.getenv("FEATURE_CHUNK_SIZE") or str(DEFAULT_KB_FEATURE_CHUNK_SIZE)
    try:
        chunk_size = int(raw_size)
    except ValueError as exc:
        raise ValueError("KB_FEATURE_CHUNK_SIZE must be an integer") from exc
    if chunk_size <= 0:
        raise ValueError("KB_FEATURE_CHUNK_SIZE must be positive")
    return chunk_size


def _read_kb_feature_max_workers_config() -> int:
    raw_workers = os.getenv("KB_FEATURE_MAX_WORKERS", str(DEFAULT_KB_FEATURE_MAX_WORKERS))
    try:
        workers = int(raw_workers)
    except ValueError as exc:
        raise ValueError("KB_FEATURE_MAX_WORKERS must be an integer") from exc
    if workers <= 0:
        raise ValueError("KB_FEATURE_MAX_WORKERS must be positive")
    return workers


def _read_index_unlocked() -> dict[str, Any]:
    ensure_knowledge_base()
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON in knowledge_base/index.json") from exc

    if isinstance(data, list):
        return {"items": data}
    if not isinstance(data, dict):
        return {"items": []}
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def _write_index_unlocked(index: dict[str, Any]) -> None:
    ensure_knowledge_base()
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _upsert_record(record: dict[str, Any]) -> None:
    with _INDEX_LOCK:
        index = _read_index_unlocked()
        items = index.setdefault("items", [])
        for position, item in enumerate(items):
            if isinstance(item, dict) and item.get("id") == record.get("id"):
                items[position] = record
                break
        else:
            items.append(record)
        _write_index_unlocked(index)


def _clear_record_directory(path: Path, expected_root: Path) -> None:
    resolved_path = path.resolve()
    resolved_root = expected_root.resolve()
    if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
        raise ValueError("Refusing to clear a directory outside the knowledge base.")
    if not resolved_path.exists():
        return
    for child in resolved_path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _resolve_relative_path(relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("Path is required.")
    root = PROJECT_ROOT.resolve()
    resolved = (PROJECT_ROOT / relative_path).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("Path escapes project root.")
    return resolved


def _relative_path(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


def _build_record_id(filename: str) -> str:
    stem = Path(filename).stem
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_").lower() or "script"
    slug = slug[:48].strip("_") or "script"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{slug}_{timestamp}_{uuid.uuid4().hex[:8]}"


def _safe_storage_filename(filename: str) -> str:
    path = Path(filename)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", path.stem).strip(" ._")
    suffix = path.suffix.lower()
    if not stem:
        stem = "script"
    return f"{stem[:120]}{suffix}"


def _safe_record_id(record_id: str) -> str:
    safe_id = Path(record_id or "").name
    if not safe_id or safe_id != record_id:
        raise ValueError("Invalid knowledge record id.")
    return safe_id


def _coerce_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str) and not value.strip():
        return []
    return [value]


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _emit_progress(
    progress_callback: ProgressCallback | None,
    stage: str,
    message: str,
    **extra: Any,
) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(stage, {"stage": stage, "message": message, **extra})
    except Exception:
        return


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
