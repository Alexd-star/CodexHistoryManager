from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import CodexStore, guess_codex_root  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex 历史管理器冒烟测试")
    parser.add_argument("--codex-root", default=str(guess_codex_root()))
    parser.add_argument("--write", action="store_true", help="执行归档/恢复回环测试，会自动备份")
    args = parser.parse_args()

    store = CodexStore(Path(args.codex_root).resolve())
    sessions = store.list_sessions(include_archived=True)
    assert sessions, "没有发现 Codex 会话"
    print(f"[OK] 发现会话：{len(sessions)} 个")

    existing = [s for s in sessions if s.file_exists]
    assert existing, "没有可读取的会话 JSONL 文件"
    session = min(existing, key=lambda s: s.file_size or 0)
    messages = store.read_messages(session, limit=20)
    print(f"[OK] 可读取会话：{session.id}，预览消息 {len(messages)} 条")

    zip_path = store.export_sessions([session.id], fmt="markdown", split=True, include_images=True)
    assert zip_path.exists() and zip_path.suffix.lower() == ".zip", "Markdown 导出失败"
    print(f"[OK] Markdown 导出：{zip_path}")

    user_only_zip = store.export_sessions([session.id], fmt="json", split=True, include_images=False, roles={"user"})
    assert user_only_zip.exists(), "按角色导出失败"
    print(f"[OK] 按用户角色导出：{user_only_zip}")

    rich_zip = store.export_sessions(
        [session.id],
        fmt="markdown",
        split=True,
        include_images=True,
        content_types={"chat_text", "images", "session_meta", "system_context", "tool_trace", "runtime_events"},
    )
    assert rich_zip.exists(), "多内容类型导出失败"
    print(f"[OK] 多内容类型导出：{rich_zip}")

    if messages and messages[0].get("text"):
        keyword = messages[0]["text"].strip()[:8]
        hits = store.search_messages(keyword, include_archived=True, roles={"user", "assistant"})
        assert isinstance(hits, list), "全文搜索返回类型错误"
        print(f"[OK] 全文搜索接口：关键词 {keyword!r}，命中会话 {len(hits)} 个")

    backup = store.create_backup([session.id], reason="smoke-test")
    assert (backup / "manifest.json").exists(), "备份清单不存在"
    print(f"[OK] 备份生成：{backup}")

    if args.write:
        old_state = session.archived
        store.archive_session(session.id, not old_state)
        store.archive_session(session.id, old_state)
        restored = store.get_session(session.id)
        assert restored and restored.archived == old_state, "归档/恢复回环后状态未还原"
        print("[OK] 归档/恢复回环测试通过")

    print("[OK] 冒烟测试完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
