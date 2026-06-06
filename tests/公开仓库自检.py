from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from app import CodexStore  # noqa: E402


SESSION_ID = "11111111-1111-4111-8111-111111111111"


def write_jsonl(path: Path) -> None:
    records = [
        {"timestamp": "2026-06-01T00:00:00Z", "type": "turn_context", "payload": {"turn_id": "turn-001"}},
        {
            "timestamp": "2026-06-01T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "请帮我导出 Codex 历史记录"}],
            },
        },
        {
            "timestamp": "2026-06-01T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "可以，已生成 Markdown 导出方案。"}],
            },
        },
        {"timestamp": "2026-06-01T00:00:03Z", "type": "event_msg", "payload": {"type": "task_complete"}},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")


def create_state_db(path: Path, rollout_path: Path) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            """
            create table threads (
                id text primary key,
                title text,
                rollout_path text,
                created_at integer,
                updated_at integer,
                updated_at_ms integer,
                archived integer,
                archived_at integer,
                source text,
                model text,
                cwd text,
                preview text
            )
            """
        )
        con.execute(
            """
            insert into threads (
                id, title, rollout_path, created_at, updated_at, updated_at_ms,
                archived, archived_at, source, model, cwd, preview
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                SESSION_ID,
                "公开仓库自检会话",
                str(rollout_path),
                1780272000,
                1780272001,
                1780272001000,
                0,
                None,
                "fixture",
                "gpt-test",
                str(ROOT),
                "公开仓库自检",
            ),
        )
        con.commit()
    finally:
        con.close()


def create_fixture(root: Path) -> CodexStore:
    rollout = root / "sessions" / "2026" / "06" / "01" / f"rollout-{SESSION_ID}.jsonl"
    write_jsonl(rollout)
    create_state_db(root / "state_5.sqlite", rollout)
    (root / "session_index.jsonl").write_text(
        json.dumps({"id": SESSION_ID, "thread_name": "公开仓库自检会话", "updated_at": "2026-06-01T00:00:02Z"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return CodexStore(root)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="codex-history-manager-test-") as temp:
        base = Path(temp)
        app_module.EXPORT_ROOT = base / "exports"
        app_module.BACKUP_ROOT = base / "backups"
        app_module.LOG_ROOT = base / "logs"
        app_module.OPERATION_LOG = app_module.LOG_ROOT / "操作日志.jsonl"

        store = create_fixture(base / ".codex")

        sessions = store.list_sessions(include_archived=True)
        assert len(sessions) == 1, f"会话数量异常：{len(sessions)}"
        session = sessions[0]
        assert session.title == "公开仓库自检会话"

        messages = store.read_messages(session, limit=10)
        assert len(messages) == 2, f"消息数量异常：{len(messages)}"
        assert messages[0]["role"] == "user"
        assert "导出 Codex 历史记录" in messages[0]["text"]

        hits = store.search_messages("Markdown", include_archived=True, roles={"assistant"})
        assert len(hits) == 1, "搜索未命中助手消息"

        exported = store.export_sessions([SESSION_ID], fmt="markdown", split=True, include_images=True)
        assert exported.exists() and exported.suffix == ".zip", "Markdown 导出失败"

        backup = store.create_backup([SESSION_ID], reason="public-fixture")
        assert (backup / "manifest.json").exists(), "备份清单不存在"

        repaired = store.repair_indexes([SESSION_ID])
        assert repaired["changed"], "索引修复没有更新任何会话"

        print("[OK] 公开仓库自检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
