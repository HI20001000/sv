from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from code_components.document_browser import SUPPORTED_EXTENSIONS, list_input_documents
from code_components.langChain import (
    build_workflow,
    invoke_response,
    make_llm,
    ping_model,
)
from code_components.script_processing import process_script_to_output


ROOT_DIR = Path(__file__).resolve().parent
INPUT_DIR = ROOT_DIR / "input_documents"
OUTPUT_DIR = ROOT_DIR / "output"
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(ENV_PATH, encoding="utf-8-sig")


class ChatRequest(BaseModel):
    message: str


class ApiState:
    def __init__(self) -> None:
        self.history: list[BaseMessage] = []
        self.pending_docs_files: list[str] = []
        self.lock = threading.Lock()
        self.workflow_lock = threading.Lock()
        self.workflow_jobs: dict[str, dict[str, Any]] = {}
        self.llm = None
        self.chain = None

    def ensure_llm_env(self) -> None:
        missing = [key for key in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY") if not os.getenv(key)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required environment variables: {', '.join(missing)}",
            )

    def ensure_chain(self):
        self.ensure_llm_env()
        if self.llm is None or self.chain is None:
            self.llm = make_llm()
            self.chain = build_workflow(self.llm)
        return self.llm, self.chain

    def create_workflow_job(self, filename: str) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "filename": filename,
            "status": "queued",
            "logs": [f"已加入 /docs 任務佇列：{filename}"],
            "result": None,
            "error": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self.workflow_lock:
            self.workflow_jobs[job_id] = job
        return dict(job)

    def get_workflow_job(self, job_id: str) -> dict[str, Any]:
        with self.workflow_lock:
            job = self.workflow_jobs.get(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Workflow job not found.")
            return dict(job)

    def append_workflow_log(self, job_id: str, message: str) -> None:
        with self.workflow_lock:
            job = self.workflow_jobs.get(job_id)
            if job is None:
                return
            logs = job.setdefault("logs", [])
            if not logs or logs[-1] != message:
                logs.append(message)
            job["updated_at"] = datetime.now().isoformat(timespec="seconds")

    def update_workflow_job(self, job_id: str, **updates: Any) -> None:
        with self.workflow_lock:
            job = self.workflow_jobs.get(job_id)
            if job is None:
                return
            job.update(updates)
            job["updated_at"] = datetime.now().isoformat(timespec="seconds")


state = ApiState()

app = FastAPI(title="Short Video AI Web API", docs_url="/api/docs", redoc_url="/api/redoc")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    has_llm_env = all(os.getenv(key) for key in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"))
    return {
        "status": "ok",
        "has_llm_env": has_llm_env,
        "input_document_count": len(list_input_documents()),
        "output_project_count": len(_list_output_projects()),
    }


@app.get("/api/input-documents")
def get_input_documents() -> dict[str, Any]:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        {
            "name": path.name,
            "extension": path.suffix.lower(),
            "size": path.stat().st_size,
        }
        for path in list_input_documents()
    ]
    return {"items": files}


@app.post("/api/input-documents")
async def upload_input_document(file: UploadFile = File(...)) -> dict[str, Any]:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required.")
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .txt and .docx files are supported.")

    target_path = INPUT_DIR / filename
    content = await file.read()
    target_path.write_bytes(content)
    return {
        "message": f"Uploaded {filename}",
        "file": {
            "name": target_path.name,
            "extension": target_path.suffix.lower(),
            "size": target_path.stat().st_size,
        },
    }


@app.delete("/api/input-documents/{filename}")
def delete_input_document(filename: str) -> dict[str, Any]:
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    target_path = INPUT_DIR / safe_name
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Document not found.")

    target_path.unlink()
    return {"message": f"Deleted {safe_name}"}


@app.get("/api/output/projects")
def get_output_projects() -> dict[str, Any]:
    return {"items": _list_output_projects()}


@app.get("/api/output/projects/{project_name}")
def get_output_project(project_name: str) -> dict[str, Any]:
    project_dir = _resolve_project_dir(project_name)
    return {
        "project": _build_project_summary(project_dir),
        "story_bible": _safe_read_json(project_dir / "story_bible.json"),
        "episodes_index": _safe_read_json(
            project_dir / "episodes" / "index.json",
            fallback={"target_episode_count": 0, "generated_episode_count": 0, "episodes": []},
        ),
        "storyboards_index": _safe_read_json(
            project_dir / "storyboards" / "index.json",
            fallback={"target_episode_count": 0, "generated_storyboard_count": 0, "episodes": []},
        ),
    }


@app.get("/api/output/projects/{project_name}/story-bible")
def get_story_bible(project_name: str) -> dict[str, Any]:
    project_dir = _resolve_project_dir(project_name)
    data = _safe_read_json(project_dir / "story_bible.json")
    return {"project": project_name, "data": data}


@app.get("/api/output/projects/{project_name}/episodes")
def get_episodes(project_name: str) -> dict[str, Any]:
    project_dir = _resolve_project_dir(project_name)
    data = _safe_read_json(project_dir / "episodes" / "index.json")
    return {"project": project_name, "data": data}


@app.get("/api/output/projects/{project_name}/episodes/{episode_no}")
def get_episode(project_name: str, episode_no: int) -> dict[str, Any]:
    project_dir = _resolve_project_dir(project_name)
    data = _safe_read_json(project_dir / "episodes" / f"episode_{episode_no:04d}.json")
    return {"project": project_name, "data": data}


@app.get("/api/output/projects/{project_name}/storyboards")
def get_storyboards(project_name: str) -> dict[str, Any]:
    project_dir = _resolve_project_dir(project_name)
    data = _safe_read_json(project_dir / "storyboards" / "index.json")
    return {"project": project_name, "data": data}


@app.get("/api/output/projects/{project_name}/storyboards/{episode_no}")
def get_storyboard(project_name: str, episode_no: int) -> dict[str, Any]:
    project_dir = _resolve_project_dir(project_name)
    data = _safe_read_json(project_dir / "storyboards" / f"episode_{episode_no:04d}_storyboard.json")
    return {"project": project_name, "data": data}


@app.post("/api/workflow/run")
def run_docs_workflow(payload: dict[str, str]) -> dict[str, Any]:
    filename = Path(payload.get("filename", "")).name
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required.")

    source_path = INPUT_DIR / filename
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Document not found.")

    state.ensure_llm_env()
    job = state.create_workflow_job(filename)
    worker = threading.Thread(
        target=_run_docs_workflow_job,
        args=(job["job_id"], source_path),
        daemon=True,
    )
    worker.start()
    return {
        "type": "workflow_started",
        "message": f"Started /docs workflow for {filename}",
        "job": job,
    }


@app.get("/api/workflow/jobs/{job_id}")
def get_workflow_job(job_id: str) -> dict[str, Any]:
    return state.get_workflow_job(job_id)


@app.post("/api/chat")
def post_chat_message(request: ChatRequest) -> dict[str, Any]:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required.")

    if message.startswith("/"):
        return _handle_command(message)

    pending_docs_response = _handle_pending_docs_selection(message)
    if pending_docs_response is not None:
        return pending_docs_response

    _, chain = state.ensure_chain()
    with state.lock:
        reply = invoke_response(chain, state.history, message)
        state.history.append(HumanMessage(content=message))
        state.history.append(AIMessage(content=reply))
        history_size = len(state.history)

    return {
        "type": "assistant",
        "content": reply,
        "history_size": history_size,
    }


def _handle_pending_docs_selection(message: str) -> dict[str, Any] | None:
    with state.lock:
        pending_files = list(state.pending_docs_files)

    if not pending_files:
        return None

    if message.lower() in {"cancel", "/cancel"}:
        with state.lock:
            state.pending_docs_files = []
        return {
            "type": "system",
            "content": "已取消 /docs 文件選擇。",
        }

    selected_filename = ""
    if message.isdigit():
        selected_index = int(message)
        if 1 <= selected_index <= len(pending_files):
            selected_filename = pending_files[selected_index - 1]
        else:
            return {
                "type": "system",
                "content": f"請輸入 1 - {len(pending_files)} 的編號，或輸入 /cancel 取消。",
            }
    elif message in pending_files:
        selected_filename = message
    else:
        return {
            "type": "system",
            "content": (
                f"目前正在等待 /docs 文件選擇。請輸入 1 - {len(pending_files)} 的編號，"
                "也可以直接輸入完整文件名，或輸入 /cancel 取消。"
            ),
        }

    with state.lock:
        state.pending_docs_files = []

    workflow_response = run_docs_workflow({"filename": selected_filename})
    return {
        "type": "workflow_started",
        "message": workflow_response["message"],
        "job": workflow_response["job"],
    }


def _handle_command(message: str) -> dict[str, Any]:
    command, _, argument = message.partition(" ")
    argument = argument.strip()

    if command == "/help":
        return {
            "type": "system",
            "content": "\n".join(
                [
                    "/help - show available commands",
                    "/clear - clear current chat history",
                    "/history - show current history size",
                    "/model - show current model config",
                    "/ping - verify LLM connectivity",
                    "/docs <filename> - run the document workflow on a file in input_documents",
                ]
            ),
        }

    if command == "/clear":
        with state.lock:
            state.history.clear()
            state.pending_docs_files = []
        return {"type": "system", "content": "Chat history cleared.", "history_size": 0}

    if command == "/history":
        return {
            "type": "system",
            "content": f"Current history message count: {len(state.history)}",
            "history_size": len(state.history),
        }

    if command == "/model":
        return {
            "type": "system",
            "content": json.dumps(
                {
                    "model": os.getenv("LLM_MODEL"),
                    "base_url": os.getenv("LLM_BASE_URL"),
                },
                ensure_ascii=False,
                indent=2,
            ),
        }

    if command == "/ping":
        llm, _ = state.ensure_chain()
        text, elapsed = ping_model(llm)
        return {
            "type": "system",
            "content": json.dumps(
                {"result": text, "elapsed_seconds": round(elapsed, 2)},
                ensure_ascii=False,
                indent=2,
            ),
        }

    if command == "/docs":
        if not argument:
            files = [path.name for path in list_input_documents()]
            if not files:
                return {
                    "type": "system",
                    "content": "No files found in input_documents. Upload a .txt or .docx file first.",
                }
            with state.lock:
                state.pending_docs_files = files
            return {
                "type": "system",
                "content": "Available files:\n" + "\n".join(
                    f"{index}. {name}" for index, name in enumerate(files, start=1)
                ) + "\n\n請輸入對應編號開始處理，或輸入 /cancel 取消。",
            }
        with state.lock:
            state.pending_docs_files = []
        workflow_response = run_docs_workflow({"filename": argument})
        return {
            "type": "workflow_started",
            "message": workflow_response["message"],
            "job": workflow_response["job"],
        }

    raise HTTPException(status_code=400, detail=f"Unsupported command: {command}")


def _run_docs_workflow_job(job_id: str, source_path: Path) -> None:
    state.update_workflow_job(job_id, status="running")
    state.append_workflow_log(job_id, f"開始處理文件：{source_path.name}")

    def on_progress(stage: str, progress_payload: dict[str, object]) -> None:
        message = str(progress_payload.get("message", stage))
        state.append_workflow_log(job_id, message)

    try:
        llm = make_llm()
        result = process_script_to_output(
            llm=llm,
            source_path=source_path,
            progress_callback=on_progress,
        )
        result_payload = {
            "project_dir": result.project_dir.name,
            "source_file": source_path.name,
            "story_bible_path": str(result.story_bible_path),
            "episodes_dir": str(result.episodes_dir),
            "storyboards_dir": str(result.storyboards_dir),
            "target_episode_count": result.target_episode_count,
            "planned_episode_count": result.planned_episode_count,
            "generated_episode_count": result.generated_episode_count,
            "generated_storyboard_count": result.generated_storyboard_count,
            "total_elapsed_seconds": result.total_elapsed_seconds,
        }
        state.append_workflow_log(job_id, f"/docs 處理完成：{source_path.name}")
        state.update_workflow_job(job_id, status="completed", result=result_payload)
    except Exception as exc:
        error_message = str(exc)
        state.append_workflow_log(job_id, f"/docs 處理失敗：{error_message}")
        state.update_workflow_job(job_id, status="failed", error=error_message)


def _list_output_projects() -> list[dict[str, Any]]:
    if not OUTPUT_DIR.exists():
        return []

    project_dirs = [path for path in OUTPUT_DIR.iterdir() if path.is_dir()]
    project_dirs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return [_build_project_summary(path) for path in project_dirs]


def _build_project_summary(project_dir: Path) -> dict[str, Any]:
    project_meta = _safe_read_json(project_dir / "project_meta.json", fallback={})
    episodes_index = _safe_read_json(project_dir / "episodes" / "index.json", fallback={})
    storyboards_index = _safe_read_json(project_dir / "storyboards" / "index.json", fallback={})
    return {
        "name": project_dir.name,
        "created_at": project_meta.get("created_at"),
        "source_file": project_meta.get("source_file"),
        "target_episode_count": episodes_index.get("target_episode_count"),
        "generated_episode_count": episodes_index.get("generated_episode_count"),
        "generated_storyboard_count": storyboards_index.get("generated_storyboard_count"),
        "has_story_bible": (project_dir / "story_bible.json").exists(),
    }


def _resolve_project_dir(project_name: str) -> Path:
    safe_name = Path(project_name).name
    if safe_name != project_name:
        raise HTTPException(status_code=400, detail="Invalid project name.")

    project_dir = OUTPUT_DIR / safe_name
    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail="Project not found.")
    return project_dir


def _safe_read_json(path: Path, fallback: Any | None = None) -> Any:
    if not path.exists():
        if fallback is not None:
            return fallback
        raise HTTPException(status_code=404, detail=f"File not found: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in {path.name}") from exc


@app.exception_handler(HTTPException)
async def handle_http_exception(_, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
