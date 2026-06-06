from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from collections import deque
from datetime import datetime, timezone, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable


if getattr(sys, "frozen", False):
    APP_ROOT = Path(sys.executable).resolve().parent
    RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT))
else:
    APP_ROOT = Path(__file__).resolve().parent
    RESOURCE_ROOT = APP_ROOT
STATIC_ROOT = RESOURCE_ROOT / "static"
APP_DATA_ENV = "CODEX_HISTORY_MANAGER_HOME"
RELEASES_API_URL = "https://api.github.com/repos/Alexd-star/CodexHistoryManager/releases/latest"
RELEASES_PAGE_URL = "https://github.com/Alexd-star/CodexHistoryManager/releases/latest"


def default_data_root() -> Path:
    override = os.environ.get(APP_DATA_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "CodexHistoryManager"
    return Path.home() / ".codex-history-manager"


DATA_ROOT = default_data_root()
EXPORT_ROOT = DATA_ROOT / "exports"
BACKUP_ROOT = DATA_ROOT / "backups"
LOG_ROOT = DATA_ROOT / "logs"
OPERATION_LOG = LOG_ROOT / "操作日志.jsonl"
APP_LOG = LOG_ROOT / "应用日志.log"
CONFIG_PATH = DATA_ROOT / "config.json"
VERSION_FILE = RESOURCE_ROOT / "VERSION"
LOCAL_TZ = timezone(timedelta(hours=8))


def read_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    return "0.0.0"


APP_VERSION = read_version()


def setup_logging() -> logging.Logger:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("codex_history_manager")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(APP_LOG, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


LOGGER = setup_logging()


def log_exception(context: str, exc: BaseException) -> None:
    LOGGER.exception("%s: %s", context, exc)


def utc_now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(value: str, fallback: str = "untitled") -> str:
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", value or "").strip(" ._")
    text = re.sub(r"\s+", "_", text)
    return (text or fallback)[:120]


def iso_to_local_text(value: str | int | float | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return str(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def epoch_to_iso(seconds: int | None) -> str:
    if not seconds:
        return ""
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def append_operation(action: str, detail: dict[str, Any]) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "action": action,
        "detail": detail,
    }
    with OPERATION_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def guess_codex_root() -> Path:
    configured = load_config().get("codex_root")
    if configured:
        path = Path(str(configured)).expanduser()
        if path.exists():
            return path
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        LOGGER.warning("load config failed: %s", exc)
        return {}


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config.update(updates)
    config["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def is_directory_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def parse_version(value: str) -> tuple[int, ...]:
    text = str(value or "").strip().lstrip("vV")
    parts: list[int] = []
    for piece in re.split(r"[.+_-]", text):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            match = re.match(r"(\d+)", piece)
            if match:
                parts.append(int(match.group(1)))
    return tuple(parts or [0])


def check_latest_release(timeout: float = 8.0) -> dict[str, Any]:
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"CodexHistoryManager/{APP_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "current_version": APP_VERSION,
            "latest_tag": "",
            "latest_version": "",
            "has_update": False,
            "release_url": RELEASES_PAGE_URL,
            "published_at": "",
            "name": "",
            "error": str(exc),
        }
    latest_tag = str(payload.get("tag_name") or "")
    latest_version = latest_tag.lstrip("vV")
    current = parse_version(APP_VERSION)
    latest = parse_version(latest_version)
    return {
        "current_version": APP_VERSION,
        "latest_tag": latest_tag,
        "latest_version": latest_version,
        "has_update": latest > current,
        "release_url": payload.get("html_url") or RELEASES_PAGE_URL,
        "published_at": payload.get("published_at") or "",
        "name": payload.get("name") or latest_tag,
    }


@dataclass
class SessionInfo:
    id: str
    title: str
    rollout_path: str
    created_at: str
    updated_at: str
    archived: bool
    source: str
    model: str
    cwd: str
    preview: str
    file_exists: bool
    file_size: int
    message_count: int | None = None
    user_count: int | None = None
    assistant_count: int | None = None


class CodexStore:
    def __init__(self, codex_root: Path):
        self.codex_root = codex_root
        self.state_db = codex_root / "state_5.sqlite"
        self.session_index = codex_root / "session_index.jsonl"
        self.sessions_root = codex_root / "sessions"
        self.archived_root = codex_root / "archived_sessions"

    def list_sessions(self, include_archived: bool = True, query: str = "") -> list[SessionInfo]:
        rows: dict[str, SessionInfo] = {}
        if self.state_db.exists():
            con = sqlite3.connect(str(self.state_db), timeout=10)
            con.row_factory = sqlite3.Row
            try:
                sql = (
                    "select id,title,rollout_path,created_at,updated_at,archived,source,model,cwd,preview "
                    "from threads"
                )
                for row in con.execute(sql):
                    path = Path(row["rollout_path"])
                    rows[row["id"]] = SessionInfo(
                        id=row["id"],
                        title=row["title"] or row["id"],
                        rollout_path=str(path),
                        created_at=epoch_to_iso(row["created_at"]),
                        updated_at=epoch_to_iso(row["updated_at"]),
                        archived=bool(row["archived"]),
                        source=row["source"] or "",
                        model=row["model"] or "",
                        cwd=row["cwd"] or "",
                        preview=row["preview"] or "",
                        file_exists=path.exists(),
                        file_size=path.stat().st_size if path.exists() else 0,
                    )
            finally:
                con.close()

        for item in self._scan_rollout_files():
            if item["id"] not in rows:
                path = Path(item["path"])
                rows[item["id"]] = SessionInfo(
                    id=item["id"],
                    title=item.get("title") or item["id"],
                    rollout_path=str(path),
                    created_at=item.get("created_at", ""),
                    updated_at=item.get("updated_at", ""),
                    archived="archived_sessions" in path.parts,
                    source="filesystem",
                    model="",
                    cwd="",
                    preview="",
                    file_exists=True,
                    file_size=path.stat().st_size if path.exists() else 0,
                )

        if self.session_index.exists():
            index_entries: dict[str, dict[str, Any]] = {}
            for entry in self._read_index():
                sid = entry.get("id", "")
                if not sid:
                    continue
                old = index_entries.get(sid)
                if not old or str(entry.get("updated_at") or "") >= str(old.get("updated_at") or ""):
                    index_entries[sid] = entry
            for sid, entry in index_entries.items():
                current = rows.get(sid)
                if current:
                    if entry.get("thread_name"):
                        current.title = entry["thread_name"]
                    if entry.get("updated_at") and entry["updated_at"] > (current.updated_at or ""):
                        current.updated_at = entry["updated_at"]

        result = list(rows.values())
        if not include_archived:
            result = [s for s in result if not s.archived]
        if query:
            q = query.lower()
            result = [
                s for s in result
                if q in s.title.lower() or q in s.id.lower() or q in s.preview.lower() or q in s.cwd.lower()
            ]
        result.sort(key=lambda s: s.updated_at or s.created_at or "", reverse=True)
        return result

    def get_session(self, session_id: str) -> SessionInfo | None:
        for session in self.list_sessions(include_archived=True):
            if session.id == session_id:
                return session
        return None

    def read_messages(self, session: SessionInfo, limit: int | None = None) -> list[dict[str, Any]]:
        path = Path(session.rollout_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if limit and limit > 0:
            return self._read_recent_messages(path, limit)
        messages: list[dict[str, Any]] | deque[dict[str, Any]]
        messages = []
        current_turn = ""
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg, current_turn = self._message_from_record(record, current_turn)
                if not msg:
                    continue
                messages.append(msg)
        return list(messages)

    def _read_recent_messages(self, path: Path, limit: int) -> list[dict[str, Any]]:
        file_size = path.stat().st_size
        chunk_size = 1024 * 1024
        max_bytes = min(file_size, 96 * 1024 * 1024)
        data = b""
        offset = file_size
        messages: list[dict[str, Any]] = []
        while offset > 0 and len(data) < max_bytes:
            read_size = min(chunk_size, offset)
            offset -= read_size
            with path.open("rb") as fh:
                fh.seek(offset)
                data = fh.read(read_size) + data
            text = data.decode("utf-8", errors="ignore")
            lines = text.splitlines()
            if offset > 0 and lines:
                lines = lines[1:]
            current_turn = ""
            messages = []
            for line in lines:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg, current_turn = self._message_from_record(record, current_turn)
                if msg:
                    messages.append(msg)
            if len(messages) >= limit:
                return messages[-limit:]
            chunk_size = min(chunk_size * 2, 16 * 1024 * 1024)
        return messages[-limit:]

    def _message_from_record(self, record: dict[str, Any], current_turn: str) -> tuple[dict[str, Any] | None, str]:
        rtype = record.get("type")
        payload = record.get("payload") or {}
        if rtype == "event_msg" and payload.get("type") == "task_started":
            return None, str(payload.get("turn_id") or current_turn)
        if rtype == "turn_context":
            return None, str((payload or {}).get("turn_id") or current_turn)
        if rtype != "response_item" or payload.get("type") != "message":
            return None, current_turn
        role = payload.get("role")
        if role not in {"user", "assistant", "developer", "system"}:
            return None, current_turn
        parts, image_items = self._message_parts(payload.get("content") or [])
        if not parts and not image_items:
            return None, current_turn
        return {
            "timestamp": record.get("timestamp") or "",
            "local_time": iso_to_local_text(record.get("timestamp")),
            "role": role,
            "phase": payload.get("phase") or "",
            "turn_id": current_turn,
            "text": "\n\n".join(parts).strip(),
            "image_count": len(image_items),
            "images": image_items,
        }, current_turn

    def read_records(self, session: SessionInfo, limit: int | None = None) -> list[dict[str, Any]]:
        path = Path(session.rollout_path)
        if not path.exists():
            raise FileNotFoundError(path)
        records: list[dict[str, Any]] | deque[dict[str, Any]]
        records = deque(maxlen=limit) if limit and limit > 0 else []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return list(records)

    def latest_message_timestamp(self, session: SessionInfo) -> str:
        path = Path(session.rollout_path)
        if not path.exists():
            return ""
        file_size = path.stat().st_size
        chunk_size = 512 * 1024
        data = b""
        offset = file_size
        max_bytes = min(file_size, 32 * 1024 * 1024)
        while offset > 0 and len(data) < max_bytes:
            read_size = min(chunk_size, offset)
            offset -= read_size
            with path.open("rb") as fh:
                fh.seek(offset)
                data = fh.read(read_size) + data
            text = data.decode("utf-8", errors="ignore")
            lines = text.splitlines()
            if offset > 0 and lines:
                lines = lines[1:]
            for line in reversed(lines):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rtype = record.get("type")
                payload = record.get("payload") or {}
                if rtype == "response_item" and payload.get("type") == "message":
                    return record.get("timestamp") or ""
                if rtype == "event_msg" and payload.get("type") in {"user_message", "agent_message", "task_complete"}:
                    return record.get("timestamp") or ""
            chunk_size = min(chunk_size * 2, 8 * 1024 * 1024)
        return ""

    def count_messages(self, session: SessionInfo) -> dict[str, int]:
        counts = {"messages": 0, "user": 0, "assistant": 0, "images": 0}
        for msg in self.read_messages(session):
            counts["messages"] += 1
            if msg["role"] == "user":
                counts["user"] += 1
            if msg["role"] == "assistant":
                counts["assistant"] += 1
            counts["images"] += int(msg.get("image_count") or 0)
        return counts

    def search_messages(
        self,
        query: str,
        include_archived: bool = True,
        roles: set[str] | None = None,
        max_hits_per_session: int = 5,
    ) -> list[dict[str, Any]]:
        query = (query or "").strip().lower()
        if not query:
            return []
        results: list[dict[str, Any]] = []
        for session in self.list_sessions(include_archived=include_archived):
            if not session.file_exists:
                continue
            hits: list[dict[str, str]] = []
            for msg in self.read_messages(session):
                if roles and msg.get("role") not in roles:
                    continue
                text = msg.get("text") or ""
                if query not in text.lower():
                    continue
                hits.append({
                    "role": msg.get("role") or "",
                    "local_time": msg.get("local_time") or "",
                    "snippet": self._snippet(text, query),
                })
                if len(hits) >= max_hits_per_session:
                    break
            if hits:
                item = session.__dict__.copy()
                item["hits"] = hits
                item["hit_count_shown"] = len(hits)
                results.append(item)
        return results

    def archive_session(self, session_id: str, archived: bool) -> dict[str, Any]:
        result = self.archive_sessions([session_id], archived)
        return {"session_id": session_id, "archived": archived, "backup": result["backup"]}

    def archive_sessions(self, session_ids: list[str], archived: bool) -> dict[str, Any]:
        valid_ids = [sid for sid in session_ids if self.get_session(sid)]
        if not valid_ids:
            raise ValueError("没有可操作的有效会话")
        backup_dir = self.create_backup(valid_ids, reason="batch-archive" if archived else "batch-restore")
        con = sqlite3.connect(str(self.state_db), timeout=15)
        try:
            archived_at = int(time.time()) if archived else None
            con.executemany(
                "update threads set archived=?, archived_at=? where id=?",
                [(1 if archived else 0, archived_at, sid) for sid in valid_ids],
            )
            con.commit()
        finally:
            con.close()
        append_operation("归档" if archived else "恢复", {
            "session_ids": valid_ids,
            "backup": str(backup_dir),
        })
        return {"session_ids": valid_ids, "archived": archived, "backup": str(backup_dir)}

    def repair_index(self, session_id: str) -> dict[str, Any]:
        result = self.repair_indexes([session_id])
        changed = result["changed"][0] if result["changed"] else None
        if not changed:
            return {"session_id": session_id, "changed": False, "reason": "no messages"}
        return {"session_id": session_id, "changed": True, "latest": changed["latest"], "backup": result["backup"]}

    def repair_indexes(self, session_ids: list[str]) -> dict[str, Any]:
        valid = [self.get_session(sid) for sid in session_ids]
        sessions = [s for s in valid if s is not None]
        if not sessions:
            raise ValueError("没有可修复的会话")
        backup_dir = self.create_backup([s.id for s in sessions], reason="repair-latest-index")
        updates: list[tuple[int, int, str]] = []
        changed: list[dict[str, str]] = []
        for session in sessions:
            latest = self.latest_message_timestamp(session)
            if not latest:
                continue
            latest_dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            latest_epoch = int(latest_dt.timestamp())
            latest_ms = int(latest_dt.timestamp() * 1000)
            updates.append((latest_epoch, latest_ms, session.id))
            changed.append({"session_id": session.id, "title": session.title, "latest": latest})
            self._upsert_index(session.id, session.title, latest)
            path = Path(session.rollout_path)
            if path.exists():
                os.utime(path, (latest_epoch, latest_epoch))
        con = sqlite3.connect(str(self.state_db), timeout=15)
        try:
            con.executemany(
                "update threads set updated_at=?, updated_at_ms=? where id=?",
                updates,
            )
            con.commit()
        finally:
            con.close()
        append_operation("恢复最新记录", {"session_ids": [s.id for s in sessions], "changed": changed, "backup": str(backup_dir)})
        return {"changed": changed, "backup": str(backup_dir)}

    def create_backup(self, session_ids: list[str] | None = None, reason: str = "manual") -> Path:
        tag = utc_now_tag()
        target = BACKUP_ROOT / f"{tag}_{safe_name(reason)}"
        target.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "codex_root": str(self.codex_root),
            "reason": reason,
            "session_ids": session_ids or [],
            "files": [],
        }
        self._copy_sqlite(self.state_db, target / "state_5.sqlite")
        self._copy_sqlite(self.codex_root / "logs_2.sqlite", target / "logs_2.sqlite")
        for p in [self.session_index, self.codex_root / "config.toml", self.codex_root / "process_manager" / "chat_processes.json"]:
            if p.exists():
                dst = target / p.name
                shutil.copy2(p, dst)
                manifest["files"].append(str(dst))
        for sid in session_ids or []:
            session = self.get_session(sid)
            if session and Path(session.rollout_path).exists():
                dst_dir = target / "sessions"
                dst_dir.mkdir(exist_ok=True)
                dst = dst_dir / Path(session.rollout_path).name
                shutil.copy2(session.rollout_path, dst)
                manifest["files"].append(str(dst))
        (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        append_operation("备份", {"reason": reason, "session_ids": session_ids or [], "backup": str(target)})
        return target

    def list_backups(self) -> list[dict[str, Any]]:
        if not BACKUP_ROOT.exists():
            return []
        items: list[dict[str, Any]] = []
        for path in BACKUP_ROOT.iterdir():
            if not path.is_dir():
                continue
            manifest_path = path / "manifest.json"
            manifest: dict[str, Any] = {}
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    manifest = {}
            items.append({
                "name": path.name,
                "path": str(path),
                "created_at": manifest.get("created_at") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                "reason": manifest.get("reason") or "",
                "session_ids": manifest.get("session_ids") or [],
                "file_count": len(manifest.get("files") or []),
            })
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return items[:100]

    def list_operations(self) -> list[dict[str, Any]]:
        if not OPERATION_LOG.exists():
            return []
        records: deque[dict[str, Any]] = deque(maxlen=100)
        with OPERATION_LOG.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return list(records)[::-1]

    def diagnostic_snapshot(self) -> dict[str, Any]:
        sessions: list[SessionInfo] = []
        session_error = ""
        try:
            sessions = self.list_sessions(include_archived=True)
        except Exception as exc:
            session_error = str(exc)
            log_exception("diagnostic list_sessions failed", exc)

        existing_sessions = [s for s in sessions if s.file_exists]
        backups = self.list_backups()
        operations = self.list_operations()
        return {
            "app": {
                "version": APP_VERSION,
                "app_root": str(APP_ROOT),
                "resource_root": str(RESOURCE_ROOT),
                "data_root": str(DATA_ROOT),
                "config_path": str(CONFIG_PATH),
                "frozen": bool(getattr(sys, "frozen", False)),
                "python": sys.version.replace("\n", " "),
                "platform": sys.platform,
            },
            "paths": {
                "codex_root": str(self.codex_root),
                "state_db": str(self.state_db),
                "session_index": str(self.session_index),
                "sessions_root": str(self.sessions_root),
                "archived_root": str(self.archived_root),
                "data_root": str(DATA_ROOT),
                "config": str(CONFIG_PATH),
                "exports": str(EXPORT_ROOT),
                "backups": str(BACKUP_ROOT),
                "logs": str(LOG_ROOT),
                "operation_log": str(OPERATION_LOG),
                "app_log": str(APP_LOG),
            },
            "exists": {
                "codex_root": self.codex_root.exists(),
                "state_db": self.state_db.exists(),
                "session_index": self.session_index.exists(),
                "sessions_root": self.sessions_root.exists(),
                "archived_root": self.archived_root.exists(),
                "data_root": DATA_ROOT.exists(),
                "config": CONFIG_PATH.exists(),
                "exports": EXPORT_ROOT.exists(),
                "backups": BACKUP_ROOT.exists(),
                "logs": LOG_ROOT.exists(),
                "operation_log": OPERATION_LOG.exists(),
                "app_log": APP_LOG.exists(),
            },
            "writable": {
                "data_root": is_directory_writable(DATA_ROOT),
                "exports": is_directory_writable(EXPORT_ROOT),
                "backups": is_directory_writable(BACKUP_ROOT),
                "logs": is_directory_writable(LOG_ROOT),
            },
            "counts": {
                "sessions": len(sessions),
                "existing_session_files": len(existing_sessions),
                "archived_sessions": sum(1 for s in sessions if s.archived),
                "missing_session_files": sum(1 for s in sessions if not s.file_exists),
                "backups": len(backups),
                "operations": len(operations),
            },
            "recent_backups": backups[:5],
            "recent_operations": operations[:8],
            "session_error": session_error,
        }

    def create_support_bundle(self, diagnostics_text: str = "") -> Path:
        tag = utc_now_tag()
        bundle_dir = self._unique_dir(EXPORT_ROOT / f"{tag}_support_bundle")
        bundle_dir.mkdir(parents=True, exist_ok=True)

        snapshot = self.diagnostic_snapshot()
        (bundle_dir / "诊断信息.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        if diagnostics_text:
            (bundle_dir / "诊断信息.txt").write_text(diagnostics_text, encoding="utf-8")
        (bundle_dir / "操作记录.json").write_text(json.dumps(self.list_operations(), ensure_ascii=False, indent=2), encoding="utf-8")
        (bundle_dir / "说明.txt").write_text(
            "\n".join([
                "Codex History Manager 客户反馈包",
                "",
                "本反馈包用于排查软件运行、路径、权限、导出、备份和会话扫描问题。",
                "反馈包不包含 Codex 会话正文，不包含 sessions/archived_sessions 下的 JSONL 原始聊天文件。",
                "其中可能包含本机路径、用户名、版本号、目录状态、最近操作元数据和应用日志尾部。",
                "发送给他人前，请确认这些路径信息可以公开。",
            ]),
            encoding="utf-8",
        )
        self._write_log_tail(APP_LOG, bundle_dir / "应用日志尾部.log")
        self._write_log_tail(OPERATION_LOG, bundle_dir / "操作日志尾部.jsonl")

        zip_path = EXPORT_ROOT / f"{bundle_dir.name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in bundle_dir.rglob("*"):
                zf.write(file, file.relative_to(bundle_dir.parent))
        append_operation("support_bundle", {"path": str(zip_path)})
        return zip_path

    @staticmethod
    def _write_log_tail(source: Path, target: Path, max_bytes: int = 256 * 1024) -> None:
        if not source.exists() or not source.is_file():
            target.write_text("日志文件不存在。", encoding="utf-8")
            return
        with source.open("rb") as fh:
            if source.stat().st_size > max_bytes:
                fh.seek(-max_bytes, os.SEEK_END)
                data = fh.read()
                prefix = b"[log truncated to last bytes]\n"
                data = prefix + data
            else:
                data = fh.read()
        target.write_text(data.decode("utf-8", errors="replace"), encoding="utf-8")

    def export_sessions(
        self,
        session_ids: list[str],
        fmt: str,
        split: bool = True,
        include_images: bool = True,
        roles: set[str] | None = None,
        keyword: str = "",
        date_from: str = "",
        date_to: str = "",
        content_types: set[str] | None = None,
    ) -> Path:
        fmt = fmt.lower()
        if fmt not in {"markdown", "html", "txt", "json"}:
            raise ValueError(f"unsupported export format: {fmt}")
        tag = utc_now_tag()
        export_dir = self._unique_dir(EXPORT_ROOT / f"{tag}_{fmt}")
        export_dir.mkdir(parents=True, exist_ok=True)
        sessions = [self.get_session(sid) for sid in session_ids]
        sessions = [s for s in sessions if s is not None]
        if not sessions:
            raise ValueError("no valid sessions selected")

        if fmt == "json":
            payload = []
            for session in sessions:
                messages = self._filter_messages(self.read_messages(session), roles, keyword, date_from, date_to)
                payload.append({
                    "session": session.__dict__,
                    "filters": self._filter_info(roles, keyword, date_from, date_to, content_types),
                    "messages": messages if self._want(content_types, "chat_text") else [],
                    "artifacts": self._extract_artifacts(session, content_types),
                })
            out = export_dir / "codex_sessions.json"
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        elif split:
            for session in sessions:
                self._export_one(session, export_dir, fmt, include_images, roles, keyword, date_from, date_to, content_types)
        else:
            out = export_dir / f"codex_sessions.{self._extension(fmt)}"
            rendered = [self._render_session(session, fmt, include_images, export_dir, roles, keyword, date_from, date_to, content_types) for session in sessions]
            out.write_text("\n\n".join(rendered), encoding="utf-8")

        zip_path = EXPORT_ROOT / f"{export_dir.name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in export_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(export_dir))
        append_operation("导出", {
            "format": fmt,
            "split": split,
            "include_images": include_images,
            "filters": self._filter_info(roles, keyword, date_from, date_to, content_types),
            "session_ids": [s.id for s in sessions],
            "zip": str(zip_path),
        })
        return zip_path

    def _unique_dir(self, base: Path) -> Path:
        if not base.exists() and not (EXPORT_ROOT / f"{base.name}.zip").exists():
            return base
        for idx in range(2, 1000):
            candidate = base.with_name(f"{base.name}_{idx:02d}")
            if not candidate.exists() and not (EXPORT_ROOT / f"{candidate.name}.zip").exists():
                return candidate
        raise RuntimeError("无法创建唯一导出目录")

    def _scan_rollout_files(self) -> Iterable[dict[str, str]]:
        for root in [self.sessions_root, self.archived_root]:
            if not root.exists():
                continue
            for path in root.rglob("rollout-*.jsonl"):
                match = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})", path.name)
                sid = match.group(1) if match else path.stem
                yield {
                    "id": sid,
                    "path": str(path),
                    "title": sid,
                    "created_at": datetime.fromtimestamp(path.stat().st_ctime, timezone.utc).isoformat().replace("+00:00", "Z"),
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                }

    def _read_index(self) -> Iterable[dict[str, Any]]:
        with self.session_index.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def _upsert_index(self, session_id: str, title: str, updated_at: str) -> None:
        entries = list(self._read_index()) if self.session_index.exists() else []
        changed = False
        for entry in entries:
            if entry.get("id") == session_id:
                entry["thread_name"] = title
                entry["updated_at"] = updated_at
                changed = True
                break
        if not changed:
            entries.append({"id": session_id, "thread_name": title, "updated_at": updated_at})
        text = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
        self.session_index.write_text(text, encoding="utf-8")

    def _message_parts(self, content: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, str]]]:
        parts: list[str] = []
        images: list[dict[str, str]] = []
        for item in content:
            ctype = item.get("type")
            if ctype == "input_image":
                url = item.get("image_url") or ""
                images.append({"image_url": url, "label": f"图片附件 {len(images) + 1}"})
                parts.append(f"[图片附件 {len(images)}]")
                continue
            text = item.get("text") or item.get("input_text") or item.get("output_text") or ""
            if text:
                parts.append(str(text).strip())
        return parts, images

    def _copy_sqlite(self, source: Path, target: Path) -> None:
        if not source.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(str(source), timeout=15)
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    def _export_one(
        self,
        session: SessionInfo,
        export_dir: Path,
        fmt: str,
        include_images: bool,
        roles: set[str] | None = None,
        keyword: str = "",
        date_from: str = "",
        date_to: str = "",
        content_types: set[str] | None = None,
    ) -> Path:
        file_name = f"{safe_name(session.title, session.id)}_{session.id}.{self._extension(fmt)}"
        out = export_dir / file_name
        out.write_text(self._render_session(session, fmt, include_images, export_dir, roles, keyword, date_from, date_to, content_types), encoding="utf-8")
        return out

    def _render_session(
        self,
        session: SessionInfo,
        fmt: str,
        include_images: bool,
        export_dir: Path,
        roles: set[str] | None = None,
        keyword: str = "",
        date_from: str = "",
        date_to: str = "",
        content_types: set[str] | None = None,
    ) -> str:
        messages = self._filter_messages(self.read_messages(session), roles, keyword, date_from, date_to)
        if fmt == "markdown":
            return self._render_markdown(session, messages, include_images, export_dir, roles, keyword, date_from, date_to, content_types)
        if fmt == "html":
            md = self._render_markdown(session, messages, include_images, export_dir, roles, keyword, date_from, date_to, content_types)
            return self._markdown_to_html(md, session.title)
        if fmt == "txt":
            lines = [f"会话：{session.title}", f"ID：{session.id}", f"更新时间：{iso_to_local_text(session.updated_at)}", ""]
            if self._want(content_types, "chat_text"):
                for msg in messages:
                    lines.append(f"[{msg['local_time']}] {self._role_name(msg['role'])}")
                    lines.append(msg["text"])
                    if msg.get("image_count") and self._want(content_types, "images"):
                        lines.append(f"[图片附件：{msg['image_count']} 个]")
                    lines.append("")
            lines.extend(self._render_artifacts_text(session, content_types))
            return "\n".join(lines)
        raise ValueError(fmt)

    def _render_markdown(
        self,
        session: SessionInfo,
        messages: list[dict[str, Any]],
        include_images: bool,
        export_dir: Path,
        roles: set[str] | None = None,
        keyword: str = "",
        date_from: str = "",
        date_to: str = "",
        content_types: set[str] | None = None,
    ) -> str:
        lines = [f"# {session.title}", ""]
        if self._want(content_types, "session_meta"):
            lines.extend([
                "## 会话基础信息",
                "",
                f"- 会话 ID：`{session.id}`",
                f"- 创建时间：{iso_to_local_text(session.created_at)}",
                f"- 更新时间：{iso_to_local_text(session.updated_at)}",
                f"- 工作目录：`{session.cwd or '未记录'}`",
                f"- 模型：{session.model or '未记录'}",
                f"- 原始文件：`{session.rollout_path}`",
                f"- 导出筛选：{self._filter_summary(roles, keyword, date_from, date_to, content_types)}",
                "",
            ])
        last_date = ""
        if self._want(content_types, "chat_text"):
            lines.extend(["## 聊天正文", ""])
            for msg in messages:
                date = (msg["local_time"] or "")[:10]
                if date and date != last_date:
                    lines.extend(["", f"### {date}", ""])
                    last_date = date
                phase = f" / {msg['phase']}" if msg.get("phase") else ""
                lines.extend([f"#### {msg['local_time']} {self._role_name(msg['role'])}{phase}", ""])
                if msg.get("turn_id"):
                    lines.extend([f"轮次 ID：`{msg['turn_id']}`", ""])
                if msg.get("text"):
                    lines.extend([msg["text"], ""])
                if include_images and self._want(content_types, "images"):
                    for idx, img in enumerate(msg.get("images") or [], 1):
                        link = self._save_export_image(img.get("image_url") or "", export_dir, msg["timestamp"], session.id, idx)
                        if link:
                            lines.extend([f"![图片附件]({link})", ""])
                elif msg.get("image_count") and self._want(content_types, "images"):
                    lines.extend([f"[图片附件：{msg['image_count']} 个，导出时未提取]", ""])
        lines.extend(self._render_artifacts_markdown(session, content_types))
        return "\n".join(lines)

    def _save_export_image(self, image_url: str, export_dir: Path, timestamp: str, session_id: str, idx: int) -> str:
        match = re.match(r"^data:image/([^;]+);base64,(.+)$", image_url, re.S)
        if not match:
            return ""
        fmt, data = match.groups()
        ext = "jpg" if fmt.lower() == "jpeg" else fmt.lower().replace("svg+xml", "svg")
        raw = base64.b64decode(data)
        digest = hashlib.sha256(raw).hexdigest()[:12]
        time_part = safe_name(iso_to_local_text(timestamp).replace(" ", "_").replace(":", ""))
        image_dir = export_dir / "images" / session_id
        image_dir.mkdir(parents=True, exist_ok=True)
        name = f"{time_part}_{idx}_{digest}.{ext}"
        path = image_dir / name
        if not path.exists():
            path.write_bytes(raw)
        return urllib.parse.quote(str(path.relative_to(export_dir)).replace("\\", "/"), safe="/")

    def _markdown_to_html(self, markdown: str, title: str) -> str:
        body_lines = []
        for line in markdown.splitlines():
            if line.startswith("# "):
                body_lines.append(f"<h1>{html.escape(line[2:])}</h1>")
            elif line.startswith("## "):
                body_lines.append(f"<h2>{html.escape(line[3:])}</h2>")
            elif line.startswith("### "):
                body_lines.append(f"<h3>{html.escape(line[4:])}</h3>")
            elif line.startswith("![") and "](" in line:
                src = line.split("](", 1)[1].rstrip(")")
                body_lines.append(f'<img src="{html.escape(src)}" alt="图片附件">')
            elif line.strip() == "":
                body_lines.append("")
            else:
                body_lines.append(f"<p>{html.escape(line)}</p>")
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{html.escape(title)}</title>"
            "<style>body{font-family:'Microsoft YaHei',Segoe UI,sans-serif;line-height:1.65;max-width:980px;margin:32px auto;padding:0 24px;color:#202124}"
            "h1,h2,h3{color:#12395f}img{max-width:100%;border:1px solid #ddd;margin:12px 0}p{white-space:pre-wrap}</style></head><body>"
            + "\n".join(body_lines)
            + "</body></html>"
        )

    def _extension(self, fmt: str) -> str:
        return {"markdown": "md", "html": "html", "txt": "txt", "json": "json"}[fmt]

    def _role_name(self, role: str) -> str:
        return {"user": "用户", "assistant": "助手", "developer": "开发者指令", "system": "系统"}.get(role, role)

    def _filter_messages(
        self,
        messages: list[dict[str, Any]],
        roles: set[str] | None = None,
        keyword: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> list[dict[str, Any]]:
        keyword_lower = (keyword or "").strip().lower()
        result: list[dict[str, Any]] = []
        for msg in messages:
            if roles and msg.get("role") not in roles:
                continue
            timestamp = str(msg.get("timestamp") or "")
            day = timestamp[:10]
            if date_from and day and day < date_from:
                continue
            if date_to and day and day > date_to:
                continue
            if keyword_lower and keyword_lower not in (msg.get("text") or "").lower():
                continue
            result.append(msg)
        return result

    def _filter_info(self, roles: set[str] | None, keyword: str, date_from: str, date_to: str, content_types: set[str] | None = None) -> dict[str, Any]:
        return {
            "roles": sorted(roles) if roles else [],
            "keyword": keyword or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "content_types": sorted(content_types) if content_types else [],
        }

    def _filter_summary(self, roles: set[str] | None, keyword: str, date_from: str, date_to: str, content_types: set[str] | None = None) -> str:
        parts = []
        if content_types:
            parts.append("内容=" + ",".join(sorted(content_types)))
        if roles:
            parts.append("角色=" + ",".join(self._role_name(r) for r in sorted(roles)))
        if keyword:
            parts.append(f"关键词={keyword}")
        if date_from or date_to:
            parts.append(f"日期={date_from or '开始'} 至 {date_to or '结束'}")
        return "；".join(parts) if parts else "未筛选，导出全量消息"

    def _snippet(self, text: str, keyword: str, radius: int = 60) -> str:
        lower = text.lower()
        idx = lower.find(keyword.lower())
        if idx < 0:
            return text[: radius * 2]
        start = max(0, idx - radius)
        end = min(len(text), idx + len(keyword) + radius)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return prefix + text[start:end].replace("\n", " ") + suffix

    def _want(self, content_types: set[str] | None, key: str) -> bool:
        return not content_types or key in content_types

    def _extract_artifacts(self, session: SessionInfo, content_types: set[str] | None = None) -> dict[str, Any]:
        records = self.read_records(session)
        artifacts: dict[str, Any] = {}
        if self._want(content_types, "system_context"):
            artifacts["system_context"] = self._collect_context(records)
        if self._want(content_types, "tool_trace"):
            artifacts["tool_trace"] = self._collect_tools(records)
        if self._want(content_types, "runtime_events"):
            artifacts["runtime_events"] = self._collect_events(records)
        return artifacts

    def _collect_context(self, records: list[dict[str, Any]]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for rec in records:
            payload = rec.get("payload") or {}
            if rec.get("type") == "session_meta":
                base = ((payload.get("base_instructions") or {}).get("text") or "")[:3000]
                if base:
                    items.append({"type": "base_instructions", "text": base})
            if rec.get("type") == "turn_context":
                slim = {k: payload.get(k) for k in ["cwd", "current_date", "timezone", "approval_policy", "model"]}
                items.append({"type": "turn_context", "text": json.dumps(slim, ensure_ascii=False)})
        return items[:50]

    def _collect_tools(self, records: list[dict[str, Any]]) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for rec in records:
            payload = rec.get("payload") or {}
            ptype = payload.get("type")
            if rec.get("type") == "response_item" and ptype in {"function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output", "web_search_call"}:
                items.append({
                    "time": iso_to_local_text(rec.get("timestamp")),
                    "type": ptype,
                    "name": str(payload.get("name") or payload.get("call_id") or ""),
                    "text": json.dumps(payload, ensure_ascii=False)[:3000],
                })
            elif rec.get("type") == "event_msg" and ptype in {"exec_command_end", "patch_apply_end", "mcp_tool_call_end", "view_image_tool_call"}:
                items.append({
                    "time": iso_to_local_text(rec.get("timestamp")),
                    "type": ptype,
                    "name": str(payload.get("call_id") or ""),
                    "text": json.dumps(payload, ensure_ascii=False)[:3000],
                })
        return items

    def _collect_events(self, records: list[dict[str, Any]]) -> list[dict[str, str]]:
        keep = {"task_started", "task_complete", "context_compacted", "token_count", "user_message", "agent_message"}
        items: list[dict[str, str]] = []
        for rec in records:
            payload = rec.get("payload") or {}
            ptype = payload.get("type")
            if rec.get("type") == "event_msg" and ptype in keep:
                text = payload.get("message") or payload.get("last_agent_message") or json.dumps(payload, ensure_ascii=False)
                items.append({"time": iso_to_local_text(rec.get("timestamp")), "type": ptype, "text": str(text)[:2000]})
        return items

    def _render_artifacts_markdown(self, session: SessionInfo, content_types: set[str] | None = None) -> list[str]:
        artifacts = self._extract_artifacts(session, content_types)
        lines: list[str] = []
        for title, key in [("系统与运行上下文", "system_context"), ("工具调用轨迹", "tool_trace"), ("运行事件", "runtime_events")]:
            items = artifacts.get(key) or []
            if not items:
                continue
            lines.extend(["", f"## {title}", ""])
            for item in items:
                head = " · ".join(str(item.get(k) or "") for k in ["time", "type", "name"] if item.get(k))
                lines.extend([f"### {head or title}", "", "```json" if key != "runtime_events" else "```text", str(item.get("text") or ""), "```", ""])
        return lines

    def _render_artifacts_text(self, session: SessionInfo, content_types: set[str] | None = None) -> list[str]:
        artifacts = self._extract_artifacts(session, content_types)
        lines: list[str] = []
        for title, key in [("系统与运行上下文", "system_context"), ("工具调用轨迹", "tool_trace"), ("运行事件", "runtime_events")]:
            items = artifacts.get(key) or []
            if not items:
                continue
            lines.extend(["", f"[{title}]", ""])
            for item in items:
                lines.append(" | ".join(str(item.get(k) or "") for k in ["time", "type", "name"] if item.get(k)))
                lines.append(str(item.get("text") or ""))
                lines.append("")
        return lines


class ApiHandler(BaseHTTPRequestHandler):
    store: CodexStore

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            params = urllib.parse.parse_qs(parsed.query)
            if path == "/":
                self._send_file(STATIC_ROOT / "index.html", "text/html; charset=utf-8")
            elif path.startswith("/static/"):
                self._send_file(STATIC_ROOT / path.removeprefix("/static/"))
            elif path == "/api/status":
                self._json({"codex_root": str(self.store.codex_root), "state_db": str(self.store.state_db), "app_root": str(APP_ROOT)})
            elif path == "/api/backups":
                self._json({"backups": self.store.list_backups()})
            elif path == "/api/operations":
                self._json({"operations": self.store.list_operations()})
            elif path == "/api/sessions":
                query = (params.get("q") or [""])[0]
                include_archived = (params.get("include_archived") or ["1"])[0] != "0"
                sessions = [s.__dict__ for s in self.store.list_sessions(include_archived=include_archived, query=query)]
                self._json({"sessions": sessions})
            elif path == "/api/search":
                query = (params.get("q") or [""])[0]
                include_archived = (params.get("include_archived") or ["1"])[0] != "0"
                roles = self._parse_roles((params.get("roles") or [""])[0])
                results = self.store.search_messages(query, include_archived=include_archived, roles=roles)
                self._json({"sessions": results})
            elif path.startswith("/api/sessions/") and path.endswith("/counts"):
                session_id = path.split("/")[3]
                session = self._require_session(session_id)
                self._json({"counts": self.store.count_messages(session)})
            elif path.startswith("/api/sessions/"):
                session_id = path.split("/")[3]
                limit = int((params.get("limit") or ["200"])[0])
                include_counts = (params.get("counts") or ["1"])[0] != "0"
                session = self._require_session(session_id)
                messages = self.store.read_messages(session, limit=limit)
                counts = self.store.count_messages(session) if include_counts else None
                self._json({"session": session.__dict__, "counts": counts, "messages": messages})
            elif path == "/download":
                target = Path((params.get("path") or [""])[0])
                self._send_download(target)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json_error(exc)

    def do_POST(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            body = self._read_json()
            path = parsed.path
            if path == "/api/backup":
                session_ids = body.get("session_ids") or []
                reason = body.get("reason") or "manual"
                backup = self.store.create_backup(session_ids, reason=reason)
                self._json({"ok": True, "backup": str(backup)})
            elif path == "/api/export":
                zip_path = self.store.export_sessions(
                    body.get("session_ids") or [],
                    body.get("format") or "markdown",
                    bool(body.get("split", True)),
                    bool(body.get("include_images", True)),
                    self._parse_roles(body.get("roles") or []),
                    body.get("keyword") or "",
                    body.get("date_from") or "",
                    body.get("date_to") or "",
                    self._parse_content_types(body.get("content_types") or []),
                )
                self._json({"ok": True, "path": str(zip_path), "download": f"/download?path={urllib.parse.quote(str(zip_path))}"})
            elif path == "/api/archive-batch":
                result = self.store.archive_sessions(body.get("session_ids") or [], bool(body.get("archived", True)))
                self._json({"ok": True, **result})
            elif path == "/api/repair-latest":
                result = self.store.repair_indexes(body.get("session_ids") or [])
                self._json({"ok": True, **result})
            elif path.startswith("/api/sessions/") and path.endswith("/archive"):
                session_id = path.split("/")[3]
                result = self.store.archive_session(session_id, bool(body.get("archived", True)))
                self._json({"ok": True, **result})
            elif path.startswith("/api/sessions/") and path.endswith("/repair-index"):
                session_id = path.split("/")[3]
                result = self.store.repair_index(session_id)
                self._json({"ok": True, **result})
            elif path == "/api/shutdown":
                self._json({"ok": True, "message": "服务正在关闭"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json_error(exc)

    def _require_session(self, session_id: str) -> SessionInfo:
        session = self.store.get_session(session_id)
        if not session:
            raise KeyError(f"session not found: {session_id}")
        return session

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _parse_roles(self, value: Any) -> set[str] | None:
        allowed = {"user", "assistant", "developer", "system"}
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
        elif isinstance(value, list):
            parts = [str(p).strip() for p in value if str(p).strip()]
        else:
            parts = []
        roles = {p for p in parts if p in allowed}
        return roles or None

    def _parse_content_types(self, value: Any) -> set[str] | None:
        allowed = {"chat_text", "images", "session_meta", "system_context", "tool_trace", "runtime_events"}
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
        elif isinstance(value, list):
            parts = [str(p).strip() for p in value if str(p).strip()]
        else:
            parts = []
        selected = {p for p in parts if p in allowed}
        return selected or None

    def _json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_error(self, exc: Exception) -> None:
        self._json({"ok": False, "error": str(exc), "type": exc.__class__.__name__}, status=500)

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_download(self, path: Path) -> None:
        resolved = path.resolve()
        allowed = [EXPORT_ROOT.resolve(), BACKUP_ROOT.resolve()]
        if not any(str(resolved).lower().startswith(str(root).lower()) for root in allowed):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not resolved.exists() or not resolved.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{resolved.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex 本地对话历史管理器")
    parser.add_argument("--codex-root", default=str(guess_codex_root()), help="Codex 数据目录，默认 ~/.codex")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    ApiHandler.store = CodexStore(Path(args.codex_root).resolve())
    server = ThreadingHTTPServer((args.host, args.port), ApiHandler)
    print(f"Codex 本地对话历史管理器已启动：http://{args.host}:{args.port}")
    print(f"Codex 数据目录：{ApiHandler.store.codex_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
