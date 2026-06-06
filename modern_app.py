from __future__ import annotations

import queue
import re
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from app import (
    BACKUP_ROOT,
    EXPORT_ROOT,
    LOG_ROOT,
    RESOURCE_ROOT,
    ApiHandler,
    CodexStore,
    SessionInfo,
    check_latest_release,
    guess_codex_root,
    iso_to_local_text,
    log_exception,
    save_config,
)


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


class ModernApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Codex 历史管理器")
        self.minsize(1280, 760)
        self.apply_window_icon()
        self.center_window(1500, 920)

        self.store = CodexStore(guess_codex_root())
        self.sessions: list[dict] = []
        self.filtered: list[dict] = []
        self.session_by_id: dict[str, dict] = {}
        self.row_widgets: dict[str, dict[str, object]] = {}
        self.current_id = ""
        self.selected_ids: set[str] = set()
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.web_server: ThreadingHTTPServer | None = None
        self.closing = False
        self._filter_after: str | None = None
        self._list_after: str | None = None
        self._list_render_token = 0
        self._preview_seq = 0
        self.logo_image = self.load_logo_image()

        self.search_text = ctk.StringVar()
        self.status_filter = ctk.StringVar(value="全部")
        self.include_archived = ctk.BooleanVar(value=True)
        self.search_user = ctk.BooleanVar(value=True)
        self.search_assistant = ctk.BooleanVar(value=True)
        self.search_developer = ctk.BooleanVar(value=False)
        self.search_system = ctk.BooleanVar(value=False)

        self.export_format = ctk.StringVar(value="markdown")
        self.export_split = ctk.BooleanVar(value=True)
        self.export_images = ctk.BooleanVar(value=True)
        self.export_user = ctk.BooleanVar(value=True)
        self.export_assistant = ctk.BooleanVar(value=True)
        self.export_developer = ctk.BooleanVar(value=False)
        self.export_system = ctk.BooleanVar(value=False)
        self.export_keyword = ctk.StringVar()
        self.export_date_from = ctk.StringVar()
        self.export_date_to = ctk.StringVar()
        self.web_port = ctk.StringVar(value="8765")
        self.preview_filter = ctk.StringVar(value="全部")
        self.preview_keyword = ctk.StringVar()
        self.preview_limit = ctk.StringVar(value="60")

        self.content_vars = {
            "chat_text": ctk.BooleanVar(value=True),
            "images": ctk.BooleanVar(value=True),
            "session_meta": ctk.BooleanVar(value=True),
            "system_context": ctk.BooleanVar(value=False),
            "tool_trace": ctk.BooleanVar(value=False),
            "runtime_events": ctk.BooleanVar(value=False),
        }

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self._poll)
        self.refresh_sessions()

    def _build_ui(self) -> None:
        self.configure(fg_color="#eef3f8")
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="#12395f", corner_radius=0, height=64)
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        header.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(header, image=self.logo_image, text="", width=38).grid(row=0, column=0, padx=(24, 10), pady=12, sticky="w")
        ctk.CTkLabel(header, text="Codex 历史管理器", font=("Microsoft YaHei UI", 22, "bold"), text_color="white").grid(row=0, column=1, pady=16, sticky="w")
        self.root_label = ctk.CTkLabel(header, text=f"数据目录：{self.store.codex_root}", text_color="#dbeafe", font=("Microsoft YaHei UI", 12))
        self.root_label.grid(row=0, column=2, padx=24, sticky="e")

        left = ctk.CTkFrame(self, fg_color="#ffffff", corner_radius=18)
        left.grid(row=1, column=0, sticky="nsew", padx=(18, 8), pady=18)
        left.grid_rowconfigure(5, weight=1)

        middle = ctk.CTkFrame(self, fg_color="#ffffff", corner_radius=18)
        middle.grid(row=1, column=1, sticky="nsew", padx=8, pady=18)
        middle.grid_rowconfigure(2, weight=1)

        right = ctk.CTkFrame(self, fg_color="#ffffff", corner_radius=18)
        right.grid(row=1, column=2, sticky="nsew", padx=(8, 18), pady=18)
        right.grid_rowconfigure(1, weight=1)

        self._build_filter_panel(left)
        self._build_list_panel(middle)
        self._build_detail_panel(right)

        self.status = ctk.CTkLabel(self, text="准备就绪", anchor="w", text_color="#667085")
        self.status.grid(row=2, column=0, columnspan=3, sticky="ew", padx=22, pady=(0, 10))

    def apply_window_icon(self) -> None:
        icon_path = RESOURCE_ROOT / "assets" / "codex_history_manager.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

    def center_window(self, width: int, height: int) -> None:
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def load_logo_image(self) -> ctk.CTkImage | None:
        path = RESOURCE_ROOT / "assets" / "codex_history_manager.png"
        if not path.exists():
            return None
        try:
            return ctk.CTkImage(light_image=Image.open(path), dark_image=Image.open(path), size=(38, 38))
        except Exception:
            return None

    def _build_filter_panel(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(parent, text="筛选与搜索", font=("Microsoft YaHei UI", 18, "bold"), text_color="#102a43").grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))
        search = ctk.CTkEntry(parent, textvariable=self.search_text, placeholder_text="搜索标题、ID、工作目录、预览文本", width=320, height=40)
        search.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 10))
        search.bind("<KeyRelease>", lambda _e: self.schedule_filter())

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))
        ctk.CTkButton(row, text="↻ 刷新", width=86, command=self.refresh_sessions).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="⌕ 全文搜索", width=118, command=self.full_text_search).pack(side="left")

        ctk.CTkLabel(parent, text="会话状态", text_color="#475467").grid(row=3, column=0, sticky="w", padx=18, pady=(8, 4))
        ctk.CTkSegmentedButton(parent, values=["全部", "活动", "归档", "文件缺失"], variable=self.status_filter, command=lambda _v: self.apply_filters()).grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 12))

        role_card = self._card(parent, 5, "全文搜索角色")
        self._switch(role_card, "用户", self.search_user, 0, 0)
        self._switch(role_card, "助手", self.search_assistant, 0, 1)
        self._switch(role_card, "开发者", self.search_developer, 1, 0)
        self._switch(role_card, "系统", self.search_system, 1, 1)

        content_card = self._card(parent, 6, "导出内容")
        specs = [
            ("聊天正文", "chat_text", "用户与助手消息正文"),
            ("图片附件", "images", "导出 data URL 图片到 images 目录"),
            ("会话基础信息", "session_meta", "标题、时间、模型、工作目录"),
            ("系统上下文", "system_context", "系统/开发者/运行上下文摘要"),
            ("工具调用轨迹", "tool_trace", "shell、补丁、搜索、MCP 调用"),
            ("运行事件", "runtime_events", "任务开始、完成、压缩、token 等事件"),
        ]
        for i, (name, key, desc) in enumerate(specs):
            item = ctk.CTkFrame(content_card, fg_color="#f8fafc", corner_radius=12)
            item.grid(row=i, column=0, sticky="ew", padx=8, pady=5)
            item.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(item, text=name, font=("Microsoft YaHei UI", 13, "bold"), text_color="#1f2a44").grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(item, text=desc, text_color="#667085", font=("Microsoft YaHei UI", 11)).grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))
            ctk.CTkSwitch(item, text="", variable=self.content_vars[key], width=44).grid(row=0, column=1, rowspan=2, padx=10)

        bottom = ctk.CTkFrame(parent, fg_color="transparent")
        bottom.grid(row=7, column=0, sticky="ew", padx=18, pady=12)
        ctk.CTkButton(bottom, text="选择数据目录", fg_color="#eef2ff", text_color="#174b75", command=self.choose_root).pack(fill="x")

    def _build_list_panel(self, parent: ctk.CTkFrame) -> None:
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
        top.grid_columnconfigure(0, weight=1)
        self.count_label = ctk.CTkLabel(top, text="会话列表", font=("Microsoft YaHei UI", 18, "bold"), text_color="#102a43")
        self.count_label.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(top, text="↟ 恢复最新", width=104, command=self.repair_filtered_latest).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(top, text="✓ 全选", width=74, command=self.select_all).grid(row=0, column=2, padx=(6, 0))
        ctk.CTkButton(top, text="清空", width=70, fg_color="#eef2ff", text_color="#174b75", command=self.clear_selection).grid(row=0, column=3, padx=(6, 0))

        hint = ctk.CTkLabel(parent, text="单击预览，双击勾选；全文搜索会扫描消息正文，可能需要等待。", text_color="#667085")
        hint.grid(row=1, column=0, sticky="w", padx=18)

        self.list_frame = ctk.CTkScrollableFrame(parent, fg_color="#f8fafc", corner_radius=14)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=18, pady=12)
        self.list_frame.grid_columnconfigure(0, weight=1)

    def _build_detail_panel(self, parent: ctk.CTkFrame) -> None:
        header = ctk.CTkFrame(parent, fg_color="#ffffff")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(header, text="← 返回列表", width=104, fg_color="#eef2ff", text_color="#174b75", command=self.clear_detail).grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 12))
        self.title_label = ctk.CTkLabel(header, text="请选择一个会话", font=("Microsoft YaHei UI", 18, "bold"), text_color="#102a43", anchor="w", justify="left", wraplength=640)
        self.title_label.grid(row=0, column=1, sticky="ew")
        self.meta_label = ctk.CTkLabel(header, text="从中间列表选择一个会话后，可在这里预览、导出和管理。", text_color="#667085", anchor="w", justify="left", wraplength=780)
        self.meta_label.grid(row=1, column=1, sticky="ew", pady=(4, 0))

        tabs = ctk.CTkTabview(parent, fg_color="#ffffff", segmented_button_fg_color="#eef2f6")
        tabs.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 12))
        tabs.add("预览")
        tabs.add("导出")
        tabs.add("管理")
        tabs.tab("预览").grid_rowconfigure(1, weight=1)
        tabs.tab("预览").grid_columnconfigure(0, weight=1)

        preview_tools = ctk.CTkFrame(tabs.tab("预览"), fg_color="#ffffff")
        preview_tools.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        preview_tools.grid_columnconfigure(2, weight=1)
        ctk.CTkSegmentedButton(preview_tools, values=["全部", "用户", "助手"], variable=self.preview_filter, command=lambda _v: self.reload_preview()).grid(row=0, column=0, sticky="w")
        ctk.CTkEntry(preview_tools, textvariable=self.preview_keyword, placeholder_text="在当前预览中筛选关键词", width=210).grid(row=0, column=1, padx=8)
        self.preview_keyword.trace_add("write", lambda *_: self.reload_preview(delay=True))
        ctk.CTkOptionMenu(preview_tools, variable=self.preview_limit, values=["30", "60", "120", "全部"], width=90, command=lambda _v: self.reload_preview()).grid(row=0, column=3, sticky="e")

        self.preview = ctk.CTkScrollableFrame(tabs.tab("预览"), fg_color="#f8fafc", corner_radius=14)
        self.preview.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        self.preview.grid_columnconfigure(0, weight=1)
        self.render_empty_preview("选择会话后显示预览。")

        self._build_export_tab(tabs.tab("导出"))
        self._build_manage_tab(tabs.tab("管理"))

    def _build_export_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        box = self._card(parent, 0, "导出设置")
        ctk.CTkLabel(box, text="格式").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ctk.CTkOptionMenu(box, variable=self.export_format, values=["markdown", "html", "txt", "json"], width=160).grid(row=0, column=1, sticky="w", padx=8)
        self._switch(box, "分会话文件", self.export_split, 1, 0)
        self._switch(box, "提取图片", self.export_images, 1, 1)

        role = self._card(parent, 1, "导出角色")
        self._switch(role, "用户", self.export_user, 0, 0)
        self._switch(role, "助手", self.export_assistant, 0, 1)
        self._switch(role, "开发者", self.export_developer, 1, 0)
        self._switch(role, "系统", self.export_system, 1, 1)

        filt = self._card(parent, 2, "关键词与时间")
        ctk.CTkEntry(filt, textvariable=self.export_keyword, placeholder_text="关键词，留空表示不过滤", height=36).grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ctk.CTkEntry(filt, textvariable=self.export_date_from, placeholder_text="开始日期 YYYY-MM-DD", height=36).grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        ctk.CTkEntry(filt, textvariable=self.export_date_to, placeholder_text="结束日期 YYYY-MM-DD", height=36).grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 8))
        filt.grid_columnconfigure((0, 1), weight=1)

        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=10, pady=12)
        ctk.CTkButton(actions, text="⇩ 导出当前", height=40, command=self.export_current).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="⇩ 导出选中", height=40, command=self.export_selected).pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="打开导出目录", height=40, fg_color="#eef2ff", text_color="#174b75", command=lambda: self.open_directory(EXPORT_ROOT)).pack(side="left")

    def _build_manage_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        ops = self._card(parent, 0, "会话管理")
        ctk.CTkButton(ops, text="归档当前", command=lambda: self.archive_ids([self.current_id], True)).grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkButton(ops, text="恢复当前", command=lambda: self.archive_ids([self.current_id], False)).grid(row=0, column=1, padx=8, pady=8)
        ctk.CTkButton(ops, text="备份当前", command=self.backup_current).grid(row=0, column=2, padx=8, pady=8)
        ctk.CTkButton(ops, text="恢复当前最新", command=self.repair_current).grid(row=0, column=3, padx=8, pady=8)
        ctk.CTkButton(ops, text="批量归档", fg_color="#f59e0b", command=lambda: self.archive_ids(list(self.selected_ids), True)).grid(row=1, column=0, padx=8, pady=8)
        ctk.CTkButton(ops, text="批量恢复", command=lambda: self.archive_ids(list(self.selected_ids), False)).grid(row=1, column=1, padx=8, pady=8)
        ctk.CTkButton(ops, text="批量备份", command=self.backup_selected).grid(row=1, column=2, padx=8, pady=8)
        ctk.CTkButton(ops, text="恢复选中最新", command=self.repair_selected_latest).grid(row=1, column=3, padx=8, pady=8)
        ctk.CTkLabel(ops, text="恢复最新：按本地 JSONL 最后一条消息校正 Codex 索引和排序，执行前自动备份。", text_color="#667085").grid(row=2, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))

        web = self._card(parent, 1, "备用 Web 服务")
        ctk.CTkEntry(web, textvariable=self.web_port, placeholder_text="端口", width=120).grid(row=0, column=0, padx=8, pady=8)
        ctk.CTkButton(web, text="启动", command=self.start_web).grid(row=0, column=1, padx=8)
        ctk.CTkButton(web, text="打开浏览器版", command=self.open_web).grid(row=0, column=2, padx=8)
        ctk.CTkButton(web, text="停止", fg_color="#ef4444", command=self.stop_web).grid(row=0, column=3, padx=8)
        ctk.CTkLabel(web, text="Web 服务只绑定 127.0.0.1，适合临时用浏览器查看。", text_color="#667085").grid(row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))

        product = self._card(parent, 2, "产品支持")
        ctk.CTkButton(product, text="生成反馈包", command=self.create_support_bundle).grid(row=1, column=0, padx=8, pady=8)
        ctk.CTkButton(product, text="检查更新", command=self.check_updates).grid(row=1, column=1, padx=8, pady=8)
        ctk.CTkButton(product, text="打开发布页", fg_color="#eef2ff", text_color="#174b75", command=lambda: webbrowser.open("https://github.com/Alexd-star/CodexHistoryManager/releases/latest")).grid(row=1, column=2, padx=8, pady=8)
        ctk.CTkLabel(product, text="反馈包只包含诊断信息、日志尾部和操作元数据，不包含聊天正文。", text_color="#667085").grid(row=2, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))

        diag = self._card(parent, 3, "诊断中心")
        diag.grid_columnconfigure(0, weight=1)
        diag_actions = ctk.CTkFrame(diag, fg_color="transparent")
        diag_actions.grid(row=1, column=0, columnspan=4, sticky="ew", padx=8, pady=(4, 8))
        ctk.CTkButton(diag_actions, text="刷新诊断", width=92, command=self.refresh_diagnostics).pack(side="left", padx=(0, 8))
        ctk.CTkButton(diag_actions, text="复制诊断", width=92, command=self.copy_diagnostics).pack(side="left", padx=(0, 8))
        ctk.CTkButton(diag_actions, text="导出目录", width=86, fg_color="#eef2ff", text_color="#174b75", command=lambda: self.open_directory(EXPORT_ROOT)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(diag_actions, text="备份目录", width=86, fg_color="#eef2ff", text_color="#174b75", command=lambda: self.open_directory(BACKUP_ROOT)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(diag_actions, text="日志目录", width=86, fg_color="#eef2ff", text_color="#174b75", command=lambda: self.open_directory(LOG_ROOT)).pack(side="left")
        self.diagnostics_box = ctk.CTkTextbox(diag, height=210, fg_color="#fbfdff", border_width=1, border_color="#e5ebf2", font=("Microsoft YaHei UI", 12), wrap="word")
        self.diagnostics_box.grid(row=2, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 10))
        self.diagnostics_text = ""
        self.refresh_diagnostics()

    def _card(self, parent: ctk.CTkFrame, row: int, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="#ffffff", border_width=1, border_color="#e5ebf2", corner_radius=16)
        frame.grid(row=row, column=0, sticky="ew", padx=18 if parent == self else 0, pady=8)
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=title, font=("Microsoft YaHei UI", 14, "bold"), text_color="#1f2a44").grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 4))
        return frame

    def _switch(self, parent: ctk.CTkFrame, text: str, var: ctk.BooleanVar, row: int, col: int) -> None:
        ctk.CTkSwitch(parent, text=text, variable=var, font=("Microsoft YaHei UI", 12)).grid(row=row + 1, column=col, sticky="w", padx=12, pady=8)

    def refresh_sessions(self) -> None:
        self.set_status("正在扫描会话...")
        try:
            self.sessions = [s.__dict__ for s in self.store.list_sessions(include_archived=self.include_archived.get())]
        except Exception as exc:
            log_exception("refresh sessions failed", exc)
            self.sessions = []
            self.render_empty_preview(f"会话扫描失败：{exc}\n\n请打开“管理 > 诊断中心”复制诊断信息，或点击“选择数据目录”重新指定 Codex 数据目录。")
            messagebox.showerror("扫描失败", f"{exc}\n\n建议：检查 Codex 数据目录是否存在，或复制诊断信息给开发者。")
        self.prepare_sessions()
        self.session_by_id = {s["id"]: s for s in self.sessions}
        self.apply_filters()
        if self.sessions:
            self.set_status(f"已载入 {len(self.sessions)} 个会话")
        else:
            self.render_empty_preview(self.first_run_message())
            self.set_status("未发现会话，请检查 Codex 数据目录")

    def prepare_sessions(self) -> None:
        for s in self.sessions:
            s["_search_blob"] = " ".join(str(s.get(k) or "") for k in ["title", "id", "cwd", "preview"]).lower()

    def schedule_filter(self) -> None:
        if self._filter_after:
            self.after_cancel(self._filter_after)
        self._filter_after = self.after(160, self.apply_filters)

    def apply_filters(self) -> None:
        self._filter_after = None
        q = self.search_text.get().strip().lower()
        mode = {"全部": "all", "活动": "active", "归档": "archived", "文件缺失": "missing"}[self.status_filter.get()]
        rows = []
        for s in self.sessions:
            if mode == "active" and s["archived"]:
                continue
            if mode == "archived" and not s["archived"]:
                continue
            if mode == "missing" and s["file_exists"]:
                continue
            hay = s.get("_search_blob") or ""
            if q and q not in hay:
                continue
            rows.append(s)
        self.filtered = rows
        self.selected_ids &= {s["id"] for s in rows}
        self.render_list()

    def render_list(self) -> None:
        if self._list_after:
            try:
                self.after_cancel(self._list_after)
            except Exception:
                pass
            self._list_after = None
        self._list_render_token += 1
        token = self._list_render_token
        self.row_widgets.clear()
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.update_count_label()
        if not self.filtered:
            is_first_run = not self.sessions
            empty = ctk.CTkFrame(self.list_frame, fg_color="#ffffff", corner_radius=16, border_width=1, border_color="#e5ebf2")
            empty.grid(row=0, column=0, sticky="ew", padx=10, pady=30)
            ctk.CTkLabel(empty, text="引" if is_first_run else "⌕", width=54, height=54, fg_color="#eef6ff", text_color="#1769aa", corner_radius=18, font=("Microsoft YaHei UI", 24, "bold")).pack(pady=(24, 8))
            ctk.CTkLabel(empty, text="尚未发现 Codex 会话数据" if is_first_run else "未找到会话", font=("Microsoft YaHei UI", 16, "bold"), text_color="#102a43").pack(pady=(0, 6))
            message = self.first_run_message() if is_first_run else "请调整关键词、状态筛选，或点击“选择数据目录”指向正确的 .codex 目录。"
            ctk.CTkLabel(empty, text=message, text_color="#667085", justify="left", wraplength=360).pack(padx=24, pady=(0, 24))
            return
        self.render_list_batch(token, 0)

    def render_list_batch(self, token: int, start: int) -> None:
        if token != self._list_render_token or self.closing:
            return
        batch_size = 80
        end = min(start + batch_size, len(self.filtered))
        for idx in range(start, end):
            self._session_row(idx, self.filtered[idx])
        if end < len(self.filtered):
            self.set_status(f"正在渲染会话列表：{end}/{len(self.filtered)}")
            self._list_after = self.after(1, lambda: self.render_list_batch(token, end))
        else:
            self._list_after = None

    def update_count_label(self) -> None:
        self.count_label.configure(text=f"会话列表  {len(self.filtered)} 个 / 已选 {len(self.selected_ids)} 个")

    def first_run_message(self) -> str:
        return (
            "当前目录下没有找到可读取的 Codex 历史记录。\n\n"
            "可按下面顺序检查：\n"
            "1. 先确认本机已经使用 Codex 产生过至少一次对话；\n"
            "2. 点击左侧“选择数据目录”，选择包含 state_5.sqlite、session_index.jsonl 或 sessions 文件夹的 .codex 目录；\n"
            "3. 如果仍然为空，打开“管理 > 诊断中心”，复制诊断信息用于排查。"
        )

    def _session_row(self, idx: int, session: dict) -> None:
        active = session["id"] == self.current_id
        selected = session["id"] in self.selected_ids
        row = ctk.CTkFrame(
            self.list_frame,
            fg_color="#eaf3ff" if active else "#ffffff",
            corner_radius=14,
            border_width=1,
            border_color="#93c5fd" if active else ("#b7c9e2" if selected else "#e5ebf2"),
        )
        row.grid(row=idx, column=0, sticky="ew", padx=8, pady=5)
        row.grid_columnconfigure(2, weight=1)
        icon_text, icon_color, icon_fg = self.session_icon(session)
        ctk.CTkLabel(row, text=icon_text, width=44, height=44, fg_color=icon_color, text_color=icon_fg, corner_radius=13, font=("Microsoft YaHei UI", 15, "bold")).grid(row=0, column=0, rowspan=3, padx=(10, 8), pady=10)
        mark = "✓" if selected else "＋"
        select_color = "#2563eb" if selected else "#eef2ff"
        select_text = "#ffffff" if selected else "#174b75"
        select_button = ctk.CTkButton(row, text=mark, width=28, height=28, corner_radius=14, fg_color=select_color, text_color=select_text, command=lambda sid=session["id"]: self.toggle_select(sid))
        select_button.grid(row=0, column=1, rowspan=2, padx=(0, 8), pady=10)
        title = self.display_title(session["title"], 54)
        if session.get("hit_count_shown"):
            title = f"[命中{session['hit_count_shown']}] {title}"
        label = ctk.CTkLabel(row, text=title, font=("Microsoft YaHei UI", 13, "bold"), text_color="#102a43", anchor="w")
        label.grid(row=0, column=2, sticky="ew", padx=(0, 10), pady=(8, 0))
        sub = self.display_title(session.get("cwd") or session.get("preview") or "未记录工作目录", 70)
        ctk.CTkLabel(row, text=sub, text_color="#667085", anchor="w", font=("Microsoft YaHei UI", 11)).grid(row=1, column=2, sticky="ew", padx=(0, 10), pady=(0, 2))

        chips = ctk.CTkFrame(row, fg_color="transparent")
        chips.grid(row=2, column=2, sticky="w", padx=(0, 10), pady=(0, 9))
        status_text = "已归档" if session["archived"] else ("缺文件" if not session.get("file_exists") else "活动")
        status_bg, status_fg = self.status_palette(session)
        self._chip(chips, status_text, status_bg, status_fg).pack(side="left", padx=(0, 6))
        self._chip(chips, iso_to_local_text(session["updated_at"]) or "无时间", "#eef2f6", "#475467").pack(side="left", padx=(0, 6))
        self._chip(chips, self.format_bytes(session["file_size"]), "#f0fdf4", "#166534").pack(side="left")
        self.row_widgets[session["id"]] = {"row": row, "select": select_button}
        row.bind("<Button-1>", lambda _e, sid=session["id"]: self.select_session(sid))
        label.bind("<Button-1>", lambda _e, sid=session["id"]: self.select_session(sid))
        row.bind("<Double-Button-1>", lambda _e, sid=session["id"]: self.toggle_select(sid))

    def refresh_row_style(self, sid: str) -> None:
        widgets = self.row_widgets.get(sid)
        session = self.session_by_id.get(sid)
        if not widgets or not session:
            return
        row = widgets.get("row")
        button = widgets.get("select")
        active = sid == self.current_id
        selected = sid in self.selected_ids
        if hasattr(row, "configure"):
            row.configure(
                fg_color="#eaf3ff" if active else "#ffffff",
                border_color="#93c5fd" if active else ("#b7c9e2" if selected else "#e5ebf2"),
            )
        if hasattr(button, "configure"):
            button.configure(
                text="✓" if selected else "＋",
                fg_color="#2563eb" if selected else "#eef2ff",
                text_color="#ffffff" if selected else "#174b75",
            )

    def select_session(self, sid: str) -> None:
        previous_id = self.current_id
        self.current_id = sid
        session = self.session_by_id.get(sid) or next((s for s in self.sessions if s["id"] == sid), None)
        if not session:
            return
        self.title_label.configure(text=self.display_title(session["title"], 72))
        self.meta_label.configure(text=f"ID：{sid}\n更新时间：{iso_to_local_text(session['updated_at'])}    状态：{'已归档' if session['archived'] else '活动'}\n工作目录：{session.get('cwd') or '未记录'}")
        if previous_id and previous_id != sid:
            self.refresh_row_style(previous_id)
        self.refresh_row_style(sid)
        self.schedule_preview_load(sid, session, self.preview_settings(), delay_ms=90)

    def preview_settings(self) -> dict:
        return {
            "limit_value": self.preview_limit.get(),
            "filter_value": self.preview_filter.get(),
            "keyword": self.preview_keyword.get().strip().lower(),
        }

    def load_preview(self, sid: str, limit_value: str = "80", filter_value: str = "全部", keyword: str = "", session_data: dict | None = None) -> dict:
        session = self.session_info_from_dict(session_data) if session_data else self.store.get_session(sid)
        if not session:
            return {"summary": "会话不存在", "messages": []}
        limit = None if limit_value == "全部" else int(limit_value)
        role_filter = {"用户": {"user"}, "助手": {"assistant"}}.get(filter_value, None)
        messages = self.store.read_messages(session, limit=limit)
        blocks: list[dict[str, str]] = []
        shown = 0
        for msg in messages:
            if role_filter and msg.get("role") not in role_filter:
                continue
            text = msg.get("text") or ""
            if keyword and keyword not in text.lower():
                continue
            shown += 1
            blocks.append({
                "index": str(shown),
                "role": self.role_name(msg["role"]),
                "role_raw": msg["role"],
                "time": msg.get("local_time") or "",
                "phase": msg.get("phase") or "",
                "turn_id": msg.get("turn_id") or "",
                "image_count": str(msg.get("image_count") or 0),
                "text": self.preview_text(text, role=msg.get("role") or "") if text else ("[仅图片消息]" if msg.get("image_count") else ""),
            })
        scope = f"最近 {len(messages)} 条消息" if limit else f"全部 {len(messages)} 条消息"
        summary = f"会话：{session.title}\n更新时间：{iso_to_local_text(session.updated_at)}\n预览范围：{scope}；当前显示 {shown} 条。完整内容请使用导出功能。"
        return {"summary": summary, "messages": blocks}

    def reload_preview(self, delay: bool = False) -> None:
        if not self.current_id:
            return
        sid = self.current_id
        settings = self.preview_settings()
        session_data = self.session_by_id.get(sid)
        self.schedule_preview_load(sid, session_data, settings, delay_ms=300 if delay else 90)

    def schedule_preview_load(self, sid: str, session_data: dict | None, settings: dict, delay_ms: int = 90) -> None:
        if hasattr(self, "_preview_after") and self._preview_after:
            try:
                self.after_cancel(self._preview_after)
            except Exception:
                pass
        seq = self.next_preview_seq()

        def start() -> None:
            self._preview_after = None
            self.run(
                "preview",
                lambda: {"seq": seq, "payload": self.load_preview(sid, session_data=session_data, **settings)},
                "正在读取预览...",
            )

        self._preview_after = self.after(delay_ms, start)

    def clear_detail(self) -> None:
        old_id = self.current_id
        self.next_preview_seq()
        self.current_id = ""
        self.title_label.configure(text="请选择一个会话")
        self.meta_label.configure(text="从中间列表选择一个会话后，可在这里预览、导出和管理。")
        self.render_empty_preview("选择会话后显示预览。")
        if old_id:
            self.refresh_row_style(old_id)

    def full_text_search(self) -> None:
        q = self.search_text.get().strip()
        if not q:
            messagebox.showinfo("提示", "请先输入关键词")
            return
        include_archived = self.include_archived.get()
        roles = self.collect_search_roles()
        self.run("search", lambda: self.store.search_messages(q, include_archived, roles), "正在全文搜索...")

    def export_current(self) -> None:
        if not self.current_id:
            messagebox.showinfo("提示", "请先选择一个会话")
            return
        self.export_ids([self.current_id])

    def export_selected(self) -> None:
        if not self.selected_ids:
            messagebox.showinfo("提示", "请先勾选会话")
            return
        self.export_ids(list(self.selected_ids))

    def export_ids(self, ids: list[str]) -> None:
        fmt = self.export_format.get()
        split = self.export_split.get()
        include_images = self.export_images.get()
        roles = self.collect_export_roles()
        keyword = self.export_keyword.get().strip()
        date_from = self.export_date_from.get().strip()
        date_to = self.export_date_to.get().strip()
        content_types = self.collect_content_types()
        self.run("message", lambda: self.store.export_sessions(
            ids,
            fmt=fmt,
            split=split,
            include_images=include_images,
            roles=roles,
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
            content_types=content_types,
        ), f"正在导出 {len(ids)} 个会话...")

    def archive_ids(self, ids: list[str], archived: bool) -> None:
        ids = [sid for sid in ids if sid]
        if not ids:
            messagebox.showinfo("提示", "请先选择或勾选会话")
            return
        action = "归档" if archived else "恢复"
        if messagebox.askyesno("确认", f"{action}前会自动备份。确定处理 {len(ids)} 个会话吗？"):
            self.run("refresh", lambda: self.store.archive_sessions(ids, archived), f"正在{action}...")

    def backup_current(self) -> None:
        if not self.current_id:
            messagebox.showinfo("提示", "请先选择一个会话")
            return
        self.run("message", lambda: self.store.create_backup([self.current_id], "modern-current"), "正在备份...")

    def backup_selected(self) -> None:
        if not self.selected_ids:
            messagebox.showinfo("提示", "请先勾选会话")
            return
        self.run("message", lambda: self.store.create_backup(list(self.selected_ids), "modern-selected"), "正在批量备份...")

    def repair_current(self) -> None:
        if not self.current_id:
            messagebox.showinfo("提示", "请先选择一个会话")
            return
        self.repair_latest([self.current_id])

    def repair_selected_latest(self) -> None:
        if not self.selected_ids:
            messagebox.showinfo("提示", "请先勾选会话")
            return
        self.repair_latest(list(self.selected_ids))

    def repair_filtered_latest(self) -> None:
        ids = [s["id"] for s in self.filtered]
        if not ids:
            messagebox.showinfo("提示", "当前列表没有会话")
            return
        self.repair_latest(ids)

    def repair_latest(self, ids: list[str]) -> None:
        if not ids:
            return
        if not messagebox.askyesno("恢复最新记录", f"将按本地 JSONL 最后一条消息校正 {len(ids)} 个会话的 Codex 索引和排序，执行前会自动备份。继续吗？"):
            return
        self.run("refresh", lambda: self.store.repair_indexes(ids), "正在恢复最新记录...")

    def start_web(self) -> None:
        if self.web_server:
            self.set_status("Web 服务已经启动")
            return
        port = int(self.web_port.get())
        ApiHandler.store = self.store
        self.web_server = ThreadingHTTPServer(("127.0.0.1", port), ApiHandler)
        threading.Thread(target=self.web_server.serve_forever, daemon=True).start()
        self.set_status(f"Web 服务已启动：http://127.0.0.1:{port}")

    def open_web(self) -> None:
        if not self.web_server:
            self.start_web()
        webbrowser.open(f"http://127.0.0.1:{self.web_port.get()}")

    def stop_web(self) -> None:
        if not self.web_server:
            self.set_status("Web 服务未启动")
            return
        server = self.web_server
        self.web_server = None
        threading.Thread(target=server.shutdown, daemon=True).start()
        server.server_close()
        self.set_status("Web 服务已停止")

    def choose_root(self) -> None:
        path = filedialog.askdirectory(title="选择 Codex 数据目录", initialdir=str(self.store.codex_root))
        if not path:
            return
        self.store = CodexStore(Path(path))
        save_config({"codex_root": str(self.store.codex_root.resolve())})
        ApiHandler.store = self.store
        self.root_label.configure(text=f"数据目录：{self.store.codex_root}")
        self.current_id = ""
        self.selected_ids.clear()
        self.refresh_sessions()
        self.refresh_diagnostics()

    def refresh_diagnostics(self) -> None:
        try:
            snapshot = self.store.diagnostic_snapshot()
            self.diagnostics_text = self.format_diagnostics(snapshot)
            if hasattr(self, "diagnostics_box"):
                self.diagnostics_box.configure(state="normal")
                self.diagnostics_box.delete("1.0", "end")
                self.diagnostics_box.insert("1.0", self.diagnostics_text)
                self.diagnostics_box.configure(state="disabled")
            self.set_status("诊断信息已刷新")
        except Exception as exc:
            log_exception("refresh diagnostics failed", exc)
            self.set_status(f"诊断刷新失败：{exc}")
            messagebox.showerror("诊断刷新失败", f"{exc}\n\n建议：打开日志目录查看 应用日志.log。")

    def copy_diagnostics(self) -> None:
        if not self.diagnostics_text:
            self.refresh_diagnostics()
        self.clipboard_clear()
        self.clipboard_append(self.diagnostics_text)
        self.set_status("诊断信息已复制到剪贴板")
        messagebox.showinfo("复制成功", "诊断信息已复制。发送给开发者前请确认其中没有你不想公开的本地路径。")

    def create_support_bundle(self) -> None:
        self.run(
            "support_bundle",
            lambda: self.store.create_support_bundle(self.diagnostics_text or self.format_diagnostics(self.store.diagnostic_snapshot())),
            "正在生成客户反馈包...",
        )

    def check_updates(self) -> None:
        self.run("update_check", check_latest_release, "正在检查最新版本...")

    def open_directory(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        webbrowser.open(str(path))

    def format_diagnostics(self, snapshot: dict) -> str:
        app_info = snapshot.get("app", {})
        paths = snapshot.get("paths", {})
        exists = snapshot.get("exists", {})
        writable = snapshot.get("writable", {})
        counts = snapshot.get("counts", {})
        lines = [
            "Codex History Manager 诊断信息",
            "=" * 36,
            f"版本：{app_info.get('version')}",
            f"运行模式：{'EXE' if app_info.get('frozen') else '源码'}",
            f"Python：{app_info.get('python')}",
            f"平台：{app_info.get('platform')}",
            "",
            "路径检查",
            "-" * 36,
            f"应用目录：{paths.get('app_root')}",
            f"资源目录：{app_info.get('resource_root')}",
            f"用户数据目录：{paths.get('data_root')} [{'可写' if writable.get('data_root') else '不可写'}]",
            f"配置文件：{paths.get('config')} [{'存在' if exists.get('config') else '缺失'}]",
            f"Codex 数据目录：{paths.get('codex_root')} [{'存在' if exists.get('codex_root') else '缺失'}]",
            f"状态数据库：{paths.get('state_db')} [{'存在' if exists.get('state_db') else '缺失'}]",
            f"会话索引：{paths.get('session_index')} [{'存在' if exists.get('session_index') else '缺失'}]",
            f"会话目录：{paths.get('sessions_root')} [{'存在' if exists.get('sessions_root') else '缺失'}]",
            f"归档目录：{paths.get('archived_root')} [{'存在' if exists.get('archived_root') else '缺失'}]",
            f"导出目录：{paths.get('exports')} [{'可写' if writable.get('exports') else '不可写'}]",
            f"备份目录：{paths.get('backups')} [{'可写' if writable.get('backups') else '不可写'}]",
            f"日志目录：{paths.get('logs')} [{'可写' if writable.get('logs') else '不可写'}]",
            "",
            "数量概览",
            "-" * 36,
            f"会话总数：{counts.get('sessions')}",
            f"可读取会话文件：{counts.get('existing_session_files')}",
            f"归档会话：{counts.get('archived_sessions')}",
            f"缺失会话文件：{counts.get('missing_session_files')}",
            f"备份记录：{counts.get('backups')}",
            f"操作记录：{counts.get('operations')}",
        ]
        if snapshot.get("session_error"):
            lines.extend(["", "会话扫描错误", "-" * 36, str(snapshot["session_error"])])

        backups = snapshot.get("recent_backups") or []
        lines.extend(["", "最近备份", "-" * 36])
        if backups:
            for item in backups:
                lines.append(f"- {item.get('created_at')} | {item.get('reason')} | {item.get('name')}")
        else:
            lines.append("- 暂无备份记录")

        operations = snapshot.get("recent_operations") or []
        lines.extend(["", "最近操作", "-" * 36])
        if operations:
            for item in operations:
                lines.append(f"- {item.get('time')} | {item.get('action')} | {item.get('detail')}")
        else:
            lines.append("- 暂无操作记录")
        return "\n".join(lines)

    def toggle_select(self, sid: str) -> None:
        if sid in self.selected_ids:
            self.selected_ids.remove(sid)
        else:
            self.selected_ids.add(sid)
        self.refresh_row_style(sid)
        self.update_count_label()

    def select_all(self) -> None:
        self.selected_ids = {s["id"] for s in self.filtered}
        for sid in list(self.row_widgets):
            self.refresh_row_style(sid)
        self.update_count_label()

    def clear_selection(self) -> None:
        old_ids = list(self.selected_ids)
        self.selected_ids.clear()
        for sid in old_ids:
            self.refresh_row_style(sid)
        self.update_count_label()

    def run(self, kind: str, func, status: str) -> None:
        self.set_status(status)
        def target() -> None:
            try:
                self.queue.put((kind, func()))
            except Exception as exc:
                log_exception(f"worker failed: {kind}", exc)
                self.queue.put(("error", exc))
        threading.Thread(target=target, daemon=True).start()

    def next_preview_seq(self) -> int:
        self._preview_seq += 1
        return self._preview_seq

    def _poll(self) -> None:
        if self.closing:
            return
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "preview":
                    if isinstance(payload, dict) and "seq" in payload:
                        if payload["seq"] != self._preview_seq:
                            continue
                        payload = payload.get("payload")
                    self.render_preview(payload if isinstance(payload, dict) else {"summary": str(payload), "messages": []})
                    self.set_status("预览已更新")
                elif kind == "search":
                    self.sessions = list(payload)
                    self.prepare_sessions()
                    self.session_by_id = {s["id"]: s for s in self.sessions}
                    self.apply_filters()
                    self.set_status(f"全文搜索完成，命中 {len(self.sessions)} 个会话")
                elif kind == "refresh":
                    self.set_status(f"操作完成：{payload}")
                    self.refresh_sessions()
                elif kind == "message":
                    self.set_status(f"操作完成：{payload}")
                    messagebox.showinfo("操作完成", str(payload))
                elif kind == "support_bundle":
                    path = Path(str(payload))
                    self.set_status(f"反馈包已生成：{path.name}")
                    self.clipboard_clear()
                    self.clipboard_append(str(path))
                    messagebox.showinfo("反馈包已生成", f"反馈包已生成，路径已复制到剪贴板：\n\n{path}\n\n发送前请确认其中的本机路径信息可以公开。")
                    self.open_directory(path.parent)
                    self.refresh_diagnostics()
                elif kind == "update_check":
                    info = dict(payload) if isinstance(payload, dict) else {}
                    if info.get("error"):
                        self.set_status("检查更新失败，可手动打开发布页")
                        if messagebox.askyesno("检查更新失败", f"无法自动检查最新版本：\n{info.get('error')}\n\n是否打开 GitHub Releases 页面手动查看？"):
                            webbrowser.open(str(info.get("release_url") or "https://github.com/Alexd-star/CodexHistoryManager/releases/latest"))
                    elif info.get("has_update"):
                        self.set_status(f"发现新版本：{info.get('latest_tag')}")
                        if messagebox.askyesno("发现新版本", f"当前版本：{info.get('current_version')}\n最新版本：{info.get('latest_tag')}\n\n是否打开下载页面？"):
                            webbrowser.open(str(info.get("release_url") or "https://github.com/Alexd-star/CodexHistoryManager/releases/latest"))
                    else:
                        self.set_status("当前已是最新版本")
                        messagebox.showinfo("检查更新", f"当前版本：{info.get('current_version')}\n最新版本：{info.get('latest_tag') or info.get('latest_version')}\n\n当前已是最新版本。")
                elif kind == "error":
                    self.set_status(f"错误：{payload}")
                    self.refresh_diagnostics()
                    messagebox.showerror("操作失败", f"{payload}\n\n建议：打开“管理 > 诊断中心”，复制诊断信息，或查看日志目录中的 应用日志.log。")
        except queue.Empty:
            pass
        if not self.closing:
            self.after(150, self._poll)

    def on_close(self) -> None:
        self.closing = True
        for name in ("_preview_after", "_filter_after", "_list_after"):
            callback_id = getattr(self, name, None)
            if callback_id:
                try:
                    self.after_cancel(callback_id)
                except Exception:
                    pass
                setattr(self, name, None)
        if self.web_server:
            try:
                self.web_server.shutdown()
                self.web_server.server_close()
            except Exception:
                pass
            self.web_server = None
        try:
            self.destroy()
        except Exception:
            pass

    def set_status(self, text: str) -> None:
        if hasattr(self, "status"):
            self.status.configure(text=text)

    def clear_preview_widgets(self) -> None:
        for child in self.preview.winfo_children():
            child.destroy()

    def render_empty_preview(self, text: str) -> None:
        self.clear_preview_widgets()
        box = ctk.CTkFrame(self.preview, fg_color="#ffffff", corner_radius=18, border_width=1, border_color="#e5ebf2")
        box.grid(row=0, column=0, sticky="ew", padx=24, pady=70)
        ctk.CTkLabel(box, text="读", width=58, height=58, fg_color="#eef6ff", text_color="#1769aa", corner_radius=18, font=("Microsoft YaHei UI", 24, "bold")).pack(pady=(26, 10))
        ctk.CTkLabel(box, text="阅读区", font=("Microsoft YaHei UI", 18, "bold"), text_color="#102a43").pack(pady=(0, 8))
        ctk.CTkLabel(box, text=text, text_color="#667085", font=("Microsoft YaHei UI", 13), justify="center", wraplength=520).pack(padx=28, pady=(0, 8))
        ctk.CTkLabel(box, text="提示：单击中间会话卡片即可预览；双击会话或点击加号可加入批量操作。", text_color="#98a2b3", font=("Microsoft YaHei UI", 11), wraplength=520).pack(padx=28, pady=(0, 26))

    def render_preview(self, payload: dict) -> None:
        self.clear_preview_widgets()
        summary = ctk.CTkFrame(self.preview, fg_color="#eef6ff", corner_radius=14, border_width=1, border_color="#bfdbfe")
        summary.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        summary.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            summary,
            text=payload.get("summary") or "",
            text_color="#1f3b57",
            font=("Microsoft YaHei UI", 12),
            justify="left",
            anchor="w",
            wraplength=720,
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=12)
        messages = payload.get("messages") or []
        if not messages:
            ctk.CTkLabel(self.preview, text="当前筛选条件下没有可显示的消息。", text_color="#667085").grid(row=1, column=0, padx=16, pady=30)
            return
        reader = ctk.CTkTextbox(
            self.preview,
            fg_color="#ffffff",
            border_color="#e5ebf2",
            border_width=1,
            corner_radius=14,
            text_color="#111827",
            font=("Microsoft YaHei UI", 13),
            wrap="word",
            height=620,
        )
        reader.grid(row=1, column=0, sticky="nsew", padx=12, pady=(4, 12))
        reader.insert("1.0", self.preview_transcript(messages))
        reader.configure(state="disabled")
        try:
            reader._textbox.tag_config("role_user", foreground="#16794c")
            reader._textbox.tag_config("role_assistant", foreground="#1769aa")
            reader._textbox.tag_config("role_meta", foreground="#667085")
        except Exception:
            pass

    @staticmethod
    def preview_transcript(messages: list[dict]) -> str:
        blocks: list[str] = []
        for idx, msg in enumerate(messages, 1):
            role = msg.get("role") or msg.get("role_raw") or "消息"
            time_text = msg.get("time") or ""
            phase = f" · {msg['phase']}" if msg.get("phase") else ""
            image = f" · 图片 {msg['image_count']}" if int(msg.get("image_count") or 0) > 0 else ""
            turn = f"\n轮次 ID：{msg['turn_id']}" if msg.get("turn_id") else ""
            text = msg.get("text") or ""
            blocks.append(
                f"{idx}. {role}    {time_text}{phase}{image}"
                f"{turn}\n"
                f"{'-' * 72}\n"
                f"{text}\n"
            )
        return "\n\n".join(blocks)

    def render_message_card(self, row: int, msg: dict) -> None:
        role_raw = msg.get("role_raw") or ""
        palette = {
            "user": ("#e8f7ef", "#16794c"),
            "assistant": ("#eef6ff", "#1769aa"),
            "developer": ("#fff7ed", "#b54708"),
            "system": ("#f4f4f5", "#52525b"),
        }.get(role_raw, ("#f8fafc", "#475467"))
        card = ctk.CTkFrame(self.preview, fg_color="#ffffff", corner_radius=14, border_width=1, border_color="#e5ebf2")
        card.grid(row=row, column=0, sticky="ew", padx=12, pady=7)
        card.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        top.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkLabel(top, text=msg.get("role") or "", fg_color=palette[0], text_color=palette[1], corner_radius=16, padx=10, pady=4, font=("Microsoft YaHei UI", 12, "bold"))
        badge.grid(row=0, column=0, sticky="w", padx=(0, 8))
        time_text = msg.get("time") or ""
        if msg.get("phase"):
            time_text += f" · {msg['phase']}"
        ctk.CTkLabel(top, text=time_text, text_color="#667085", anchor="w").grid(row=0, column=1, sticky="ew")
        if int(msg.get("image_count") or 0) > 0:
            ctk.CTkLabel(top, text=f"图片 {msg['image_count']}", fg_color="#eef2ff", text_color="#174b75", corner_radius=14, padx=8, pady=3).grid(row=0, column=2)
        if msg.get("turn_id"):
            ctk.CTkLabel(card, text=f"轮次 ID：{msg['turn_id']}", text_color="#98a2b3", anchor="w").grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        text_box = ctk.CTkFrame(card, fg_color="#fbfdff" if role_raw == "assistant" else "#ffffff", corner_radius=10)
        text_box.grid(row=2, column=0, sticky="ew", padx=14, pady=(4, 14))
        text_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            text_box,
            text=msg.get("text") or "",
            text_color="#111827",
            font=("Microsoft YaHei UI", 13),
            justify="left",
            anchor="w",
            wraplength=720,
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=10)

    def collect_content_types(self) -> set[str] | None:
        selected = {k for k, v in self.content_vars.items() if v.get()}
        return selected or None

    def collect_export_roles(self) -> set[str] | None:
        roles = set()
        if self.export_user.get(): roles.add("user")
        if self.export_assistant.get(): roles.add("assistant")
        if self.export_developer.get(): roles.add("developer")
        if self.export_system.get(): roles.add("system")
        return roles or None

    def collect_search_roles(self) -> set[str] | None:
        roles = set()
        if self.search_user.get(): roles.add("user")
        if self.search_assistant.get(): roles.add("assistant")
        if self.search_developer.get(): roles.add("developer")
        if self.search_system.get(): roles.add("system")
        return roles or None

    @staticmethod
    def _chip(parent: ctk.CTkFrame, text: str, bg: str, fg: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, fg_color=bg, text_color=fg, corner_radius=12, padx=8, pady=2, font=("Microsoft YaHei UI", 10, "bold"))

    @staticmethod
    def status_palette(session: dict) -> tuple[str, str]:
        if not session.get("file_exists"):
            return "#fef2f2", "#b42318"
        if session.get("archived"):
            return "#fff7ed", "#b54708"
        return "#ecfdf3", "#067647"

    @staticmethod
    def session_info_from_dict(data: dict | None) -> SessionInfo | None:
        if not data:
            return None
        return SessionInfo(
            id=data.get("id", ""),
            title=data.get("title", ""),
            rollout_path=data.get("rollout_path", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            archived=bool(data.get("archived")),
            source=data.get("source", ""),
            model=data.get("model", ""),
            cwd=data.get("cwd", ""),
            preview=data.get("preview", ""),
            file_exists=bool(data.get("file_exists")),
            file_size=int(data.get("file_size") or 0),
            message_count=data.get("message_count"),
            user_count=data.get("user_count"),
            assistant_count=data.get("assistant_count"),
        )

    @staticmethod
    def role_name(role: str) -> str:
        return {"user": "用户", "assistant": "助手", "developer": "开发者", "system": "系统"}.get(role, role)

    @staticmethod
    def session_icon(session: dict) -> tuple[str, str, str]:
        text = f"{session.get('title') or ''} {session.get('cwd') or ''}".lower()
        rules = [
            (("东方杯", "断层", "fault", "bgpcup"), ("断", "#1d4ed8", "#ffffff")),
            (("ai", "人工智能", "智能"), ("AI", "#7c3aed", "#ffffff")),
            (("论文", "文献", "研究", "paper"), ("文", "#0f766e", "#ffffff")),
            (("操作系统", "系统赛题", "记忆"), ("OS", "#334155", "#ffffff")),
            (("金融", "创新大赛"), ("金", "#b45309", "#ffffff")),
            (("机器学习", "模型", "训练"), ("ML", "#be185d", "#ffffff")),
            (("代码", "codex", "开发", "app"), ("码", "#2563eb", "#ffffff")),
            (("数据", "统计", "建模"), ("数", "#15803d", "#ffffff")),
            (("网络", "路由", "wan"), ("网", "#0369a1", "#ffffff")),
        ]
        for keys, icon in rules:
            if any(k.lower() in text for k in keys):
                return icon
        title = str(session.get("title") or "会话").strip()
        first = title[0].upper() if title else "会"
        return (first, "#e0f2fe", "#075985")

    @staticmethod
    def display_title(text: str, limit: int = 60) -> str:
        clean = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
        return clean if len(clean) <= limit else clean[: limit - 1] + "..."

    @staticmethod
    def preview_text(text: str, limit: int = 3600, role: str = "") -> str:
        raw = str(text or "").strip()
        raw_omitted = 0
        raw_limit = max(limit * 3, 9000)
        if len(raw) > raw_limit:
            raw_omitted = len(raw) - raw_limit
            raw = raw[:raw_limit]
        clean = ModernApp.format_for_reading(raw)
        if len(clean) <= limit:
            if raw_omitted:
                return f"{clean}\n\n[预览已折叠：后续 {raw_omitted} 个字符未显示。完整内容请导出查看。]"
            return clean
        head = clean[:limit]
        omitted = len(clean) - limit + raw_omitted
        return f"{head}\n\n[预览已折叠：后续 {omitted} 个字符未显示。完整内容请导出查看。]"

    @staticmethod
    def format_for_reading(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        lines: list[str] = []
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                lines.append("")
                continue
            lines.extend(ModernApp.wrap_reading_line(line))
        result = "\n".join(lines)
        result = re.sub(r"\n{4,}", "\n\n\n", result)
        return result.strip()

    @staticmethod
    def wrap_reading_line(line: str, width: int = 84) -> list[str]:
        if len(line) <= width:
            return [line]
        line = re.sub(r"([。！？；])", r"\1\n", line)
        line = re.sub(r"([，、])(?=[^\n]{28,})", r"\1\n", line)
        line = re.sub(r"(\s+-{1,2}[A-Za-z0-9_-]+)", r"\n\1", line)
        result: list[str] = []
        for raw in line.split("\n"):
            raw = raw.strip()
            while len(raw) > width:
                cut = max(
                    raw.rfind(" ", 0, width),
                    raw.rfind("/", 0, width),
                    raw.rfind("\\", 0, width),
                    raw.rfind(",", 0, width),
                    raw.rfind("，", 0, width),
                )
                if cut < 32:
                    cut = width
                result.append(raw[:cut].rstrip())
                raw = raw[cut:].lstrip()
            if raw:
                result.append(raw)
        return result or [line]

    @staticmethod
    def format_bytes(value: int) -> str:
        n = float(value or 0)
        units = ["B", "KiB", "MiB", "GiB"]
        idx = 0
        while n >= 1024 and idx < len(units) - 1:
            n /= 1024
            idx += 1
        return f"{n:.0f} {units[idx]}" if idx == 0 else f"{n:.2f} {units[idx]}"


def main() -> None:
    app = ModernApp()
    app.mainloop()


if __name__ == "__main__":
    main()
