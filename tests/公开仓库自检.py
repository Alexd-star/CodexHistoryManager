from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_APP_HOME = Path(tempfile.mkdtemp(prefix="codex-history-manager-home-"))
os.environ["CODEX_HISTORY_MANAGER_HOME"] = str(TEST_APP_HOME)

import app as app_module  # noqa: E402
from app import CodexStore, guess_codex_root, parse_version, save_config  # noqa: E402


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
    try:
        with tempfile.TemporaryDirectory(prefix="codex-history-manager-test-") as temp:
            base = Path(temp)
            app_module.DATA_ROOT = base / "appdata"
            app_module.EXPORT_ROOT = app_module.DATA_ROOT / "exports"
            app_module.BACKUP_ROOT = app_module.DATA_ROOT / "backups"
            app_module.LOG_ROOT = app_module.DATA_ROOT / "logs"
            app_module.OPERATION_LOG = app_module.LOG_ROOT / "操作日志.jsonl"
            app_module.APP_LOG = app_module.LOG_ROOT / "应用日志.log"
            app_module.CONFIG_PATH = app_module.DATA_ROOT / "config.json"

            store = create_fixture(base / ".codex")
            save_config({"codex_root": str(store.codex_root)})
            assert guess_codex_root() == store.codex_root, "配置中的 Codex 目录未被优先使用"

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
            assert app_module.EXPORT_ROOT in exported.parents, "导出文件没有写入用户数据目录"

            backup = store.create_backup([SESSION_ID], reason="public-fixture")
            assert (backup / "manifest.json").exists(), "备份清单不存在"
            assert app_module.BACKUP_ROOT in backup.parents, "备份文件没有写入用户数据目录"

            snapshot = store.diagnostic_snapshot()
            assert snapshot["exists"]["config"], "诊断信息未识别配置文件"
            assert snapshot["writable"]["exports"], "导出目录不可写"

            support_zip = store.create_support_bundle("fixture diagnostics")
            assert support_zip.exists(), "反馈包未生成"
            with zipfile.ZipFile(support_zip) as zf:
                names = set(zf.namelist())
                joined = "\n".join(names)
                assert any(name.endswith("诊断信息.json") for name in names), "反馈包缺少诊断 JSON"
                assert any(name.endswith("说明.txt") for name in names), "反馈包缺少说明文件"
                assert "rollout-" not in joined and ".jsonl" not in joined.replace("操作日志尾部.jsonl", ""), "反馈包不应包含会话 JSONL"

            repaired = store.repair_indexes([SESSION_ID])
            assert repaired["changed"], "索引修复没有更新任何会话"

            assert parse_version("v0.1.10") > parse_version("0.1.2"), "版本比较异常"

            old_export = app_module.EXPORT_ROOT / "old_export.txt"
            new_export = app_module.EXPORT_ROOT / "new_export.txt"
            old_export.write_text("old", encoding="utf-8")
            new_export.write_text("new", encoding="utf-8")
            old_time = time.time() - 40 * 24 * 60 * 60
            os.utime(old_export, (old_time, old_time))
            cleanup = store.cleanup_old_exports(30)
            assert cleanup["removed_count"] >= 1, "旧导出清理没有删除任何项目"
            assert not old_export.exists(), "旧导出文件未被删除"
            assert new_export.exists(), "新导出文件不应被删除"
            storage = store.storage_snapshot()
            assert storage["directories"]["exports"]["bytes"] >= 0, "存储统计异常"

            print("[OK] public repository self check passed")
        return 0
    finally:
        shutil.rmtree(TEST_APP_HOME, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
