from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, Text, BOTH, END, LEFT, RIGHT, X, Y, filedialog, messagebox
from tkinter import ttk

from app import APP_ROOT, ApiHandler, CodexStore, guess_codex_root, iso_to_local_text


class DesktopApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Codex 本地对话历史管理器")
        self.root.geometry("1280x820")
        self.root.minsize(1120, 680)

        self.store = CodexStore(guess_codex_root())
        self.sessions: list[dict] = []
        self.filtered: list[dict] = []
        self.current_id = ""
        self.selected_ids: set[str] = set()
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.search_var = StringVar()
        self.status_filter_var = StringVar(value="全部")
        self.include_archived_var = BooleanVar(value=True)
        self.export_format_var = StringVar(value="markdown")
        self.export_split_var = BooleanVar(value=True)
        self.export_images_var = BooleanVar(value=True)
        self.export_user_var = BooleanVar(value=True)
        self.export_assistant_var = BooleanVar(value=True)
        self.export_developer_var = BooleanVar(value=False)
        self.export_system_var = BooleanVar(value=False)
        self.search_user_var = BooleanVar(value=True)
        self.search_assistant_var = BooleanVar(value=True)
        self.search_developer_var = BooleanVar(value=False)
        self.search_system_var = BooleanVar(value=False)
        self.export_keyword_var = StringVar()
        self.export_date_from_var = StringVar()
        self.export_date_to_var = StringVar()
        self.web_port_var = StringVar(value="8765")
        self.web_server: ThreadingHTTPServer | None = None
        self.web_thread: threading.Thread | None = None

        self._build_style()
        self._build_layout()
        self._poll_worker()
        self.refresh_sessions()

    def _build_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        self.root.configure(bg="#f4f6f8")
        style.configure(".", font=("Microsoft YaHei UI", 9), background="#f4f6f8", foreground="#1f2937")
        style.configure("Shell.TFrame", background="#f4f6f8")
        style.configure("Panel.TFrame", background="#ffffff", relief="flat")
        style.configure("Header.TFrame", background="#12395f")
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 14, "bold"), background="#12395f", foreground="#ffffff")
        style.configure("Subtle.TLabel", background="#ffffff", foreground="#667085")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"), background="#ffffff", foreground="#111827")
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 10, "bold"), background="#ffffff", foreground="#344054")
        style.configure("TButton", font=("Microsoft YaHei UI", 9), padding=(10, 6))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=(12, 6))
        style.configure("Treeview", rowheight=32, font=("Microsoft YaHei UI", 9), background="#ffffff", fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"), background="#eef2f6", foreground="#344054", relief="flat")
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#0f172a")])
        style.configure("TNotebook", background="#ffffff", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8), font=("Microsoft YaHei UI", 9))
        style.configure("TLabelframe", background="#ffffff", bordercolor="#d7dde5")
        style.configure("TLabelframe.Label", background="#ffffff", foreground="#344054", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_layout(self) -> None:
        top = ttk.Frame(self.root, style="Header.TFrame", padding=(16, 12))
        top.pack(fill=X)
        ttk.Label(top, text="Codex 历史管理器", style="Header.TLabel").pack(side=LEFT)
        self.root_info = ttk.Label(top, text=f"数据目录：{self.store.codex_root}", style="Header.TLabel", font=("Microsoft YaHei UI", 9))
        self.root_info.pack(side=RIGHT)

        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(fill=BOTH, expand=True, padx=14, pady=14)

        left = ttk.Frame(main, padding=12, style="Panel.TFrame")
        right = ttk.Frame(main, padding=12, style="Panel.TFrame")
        main.add(left, weight=2)
        main.add(right, weight=3)

        ttk.Label(left, text="会话列表", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        filter_bar = ttk.Frame(left)
        filter_bar.pack(fill=X, pady=(0, 8))
        search = ttk.Entry(filter_bar, textvariable=self.search_var)
        search.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        search.bind("<KeyRelease>", lambda _event: self.apply_filters())
        ttk.Button(filter_bar, text="刷新", command=self.refresh_sessions).pack(side=LEFT, padx=(0, 6))
        ttk.Button(filter_bar, text="全文搜索", command=self.full_text_search, style="Primary.TButton").pack(side=LEFT)

        filter_bar2 = ttk.Frame(left)
        filter_bar2.pack(fill=X, pady=(0, 8))
        ttk.Checkbutton(filter_bar2, text="显示已归档", variable=self.include_archived_var, command=self.refresh_sessions).pack(side=LEFT)
        status = ttk.Combobox(
            filter_bar2,
            textvariable=self.status_filter_var,
            values=("全部", "活动", "归档", "文件缺失"),
            width=12,
            state="readonly",
        )
        status.pack(side=LEFT, padx=8)
        status.bind("<<ComboboxSelected>>", lambda _event: self.apply_filters())
        ttk.Label(filter_bar2, text="按会话状态筛选", style="Subtle.TLabel").pack(side=LEFT)

        filter_bar3 = ttk.Frame(left)
        filter_bar3.pack(fill=X, pady=(0, 8))
        ttk.Label(filter_bar3, text="全文搜索角色").pack(side=LEFT, padx=(0, 6))
        ttk.Checkbutton(filter_bar3, text="用户", variable=self.search_user_var).pack(side=LEFT)
        ttk.Checkbutton(filter_bar3, text="助手", variable=self.search_assistant_var).pack(side=LEFT)
        ttk.Checkbutton(filter_bar3, text="开发者", variable=self.search_developer_var).pack(side=LEFT)
        ttk.Checkbutton(filter_bar3, text="系统", variable=self.search_system_var).pack(side=LEFT)

        columns = ("selected", "title", "updated", "state", "size")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("selected", text="选")
        self.tree.heading("title", text="会话标题")
        self.tree.heading("updated", text="更新时间")
        self.tree.heading("state", text="状态")
        self.tree.heading("size", text="大小")
        self.tree.column("selected", width=40, anchor="center", stretch=False)
        self.tree.column("title", width=360)
        self.tree.column("updated", width=150, stretch=False)
        self.tree.column("state", width=64, stretch=False)
        self.tree.column("size", width=76, stretch=False)
        self.tree.pack(fill=BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", self.toggle_current_selection)

        batch = ttk.Frame(left)
        batch.pack(fill=X, pady=(8, 0))
        ttk.Button(batch, text="勾选/取消", command=self.toggle_current_selection).pack(side=LEFT, padx=(0, 6))
        ttk.Button(batch, text="全选当前列表", command=self.select_all_filtered).pack(side=LEFT, padx=(0, 6))
        ttk.Button(batch, text="清空选择", command=self.clear_selection).pack(side=LEFT)

        self.detail_title = ttk.Label(right, text="请选择一个会话", style="Title.TLabel")
        self.detail_title.pack(fill=X)
        self.detail_meta = ttk.Label(right, text="", style="Subtle.TLabel", wraplength=680)
        self.detail_meta.pack(fill=X, pady=(4, 8))

        actions = ttk.Frame(right)
        actions.pack(fill=X, pady=(0, 10))
        ttk.Button(actions, text="归档", command=lambda: self.archive_current(True)).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text="恢复", command=lambda: self.archive_current(False)).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text="备份", command=self.backup_current).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text="修复索引", command=self.repair_current).pack(side=LEFT, padx=(0, 6))
        ttk.Button(actions, text="打开导出目录", command=lambda: webbrowser.open(str(APP_ROOT / "exports"))).pack(side=LEFT)

        notebook = ttk.Notebook(right)
        notebook.pack(fill=BOTH, expand=True)

        preview_tab = ttk.Frame(notebook, padding=10, style="Panel.TFrame")
        export_tab = ttk.Frame(notebook, padding=10, style="Panel.TFrame")
        web_tab = ttk.Frame(notebook, padding=10, style="Panel.TFrame")
        notebook.add(preview_tab, text="会话预览")
        notebook.add(export_tab, text="导出与批量")
        notebook.add(web_tab, text="Web 服务")

        tools = ttk.LabelFrame(export_tab, text="导出设置", padding=10)
        tools.pack(fill=X, pady=(0, 10))
        ttk.Label(tools, text="格式").pack(side=LEFT)
        ttk.Combobox(
            tools,
            textvariable=self.export_format_var,
            values=("markdown", "html", "txt", "json"),
            width=12,
            state="readonly",
        ).pack(side=LEFT, padx=(4, 10))
        ttk.Checkbutton(tools, text="分会话文件", variable=self.export_split_var).pack(side=LEFT, padx=(0, 8))
        ttk.Checkbutton(tools, text="提取图片", variable=self.export_images_var).pack(side=LEFT, padx=(0, 12))
        ttk.Button(tools, text="导出当前", command=self.export_current).pack(side=LEFT, padx=(0, 6))
        ttk.Button(tools, text="导出选中", command=self.export_selected).pack(side=LEFT, padx=(0, 6))
        ttk.Button(tools, text="批量备份", command=self.backup_selected).pack(side=LEFT, padx=(0, 6))
        ttk.Button(tools, text="批量归档", command=lambda: self.archive_selected(True)).pack(side=LEFT, padx=(0, 6))
        ttk.Button(tools, text="批量恢复", command=lambda: self.archive_selected(False)).pack(side=LEFT)

        export_filters = ttk.LabelFrame(export_tab, text="导出筛选", padding=10)
        export_filters.pack(fill=X, pady=(0, 10))
        ttk.Label(export_filters, text="角色").pack(side=LEFT, padx=(0, 4))
        ttk.Checkbutton(export_filters, text="用户", variable=self.export_user_var).pack(side=LEFT)
        ttk.Checkbutton(export_filters, text="助手", variable=self.export_assistant_var).pack(side=LEFT)
        ttk.Checkbutton(export_filters, text="开发者", variable=self.export_developer_var).pack(side=LEFT)
        ttk.Checkbutton(export_filters, text="系统", variable=self.export_system_var).pack(side=LEFT, padx=(0, 10))
        ttk.Label(export_filters, text="关键词").pack(side=LEFT)
        ttk.Entry(export_filters, textvariable=self.export_keyword_var, width=16).pack(side=LEFT, padx=(4, 8))
        ttk.Label(export_filters, text="日期").pack(side=LEFT)
        ttk.Entry(export_filters, textvariable=self.export_date_from_var, width=11).pack(side=LEFT, padx=(4, 2))
        ttk.Label(export_filters, text="至").pack(side=LEFT)
        ttk.Entry(export_filters, textvariable=self.export_date_to_var, width=11).pack(side=LEFT, padx=(2, 0))

        web_tools = ttk.LabelFrame(web_tab, text="备用浏览器版端口", padding=10)
        web_tools.pack(fill=X, pady=(0, 8))
        ttk.Label(web_tools, text="端口").pack(side=LEFT)
        ttk.Entry(web_tools, textvariable=self.web_port_var, width=8).pack(side=LEFT, padx=(4, 8))
        ttk.Button(web_tools, text="启动 Web 服务", command=self.start_web_server).pack(side=LEFT, padx=(0, 6))
        ttk.Button(web_tools, text="打开浏览器版", command=self.open_web_ui).pack(side=LEFT, padx=(0, 6))
        ttk.Button(web_tools, text="停止 Web 服务", command=self.stop_web_server).pack(side=LEFT)
        ttk.Label(web_tab, text="说明：Web 服务只绑定 127.0.0.1，本机浏览器可访问。关闭端口后页面会断开，需要在这里重新启动。", style="Subtle.TLabel", wraplength=760).pack(fill=X, pady=(8, 0))

        preview_frame = ttk.Frame(preview_tab, style="Panel.TFrame")
        preview_frame.pack(fill=BOTH, expand=True)
        self.preview = Text(preview_frame, wrap="word", font=("Microsoft YaHei UI", 10), undo=False)
        self.preview.pack(side=LEFT, fill=BOTH, expand=True)
        scroll = ttk.Scrollbar(preview_frame, command=self.preview.yview)
        scroll.pack(side=RIGHT, fill=Y)
        self.preview.configure(yscrollcommand=scroll.set)

        bottom = ttk.Frame(self.root, padding=(14, 0, 14, 12), style="Shell.TFrame")
        bottom.pack(fill=X)
        self.status_label = ttk.Label(bottom, text="准备就绪")
        self.status_label.pack(side=LEFT)
        ttk.Button(bottom, text="选择其他 Codex 数据目录", command=self.choose_codex_root).pack(side=RIGHT)

    def refresh_sessions(self) -> None:
        self.set_status("正在扫描本地 Codex 会话...")
        try:
            sessions = self.store.list_sessions(include_archived=self.include_archived_var.get())
            self.sessions = [s.__dict__ for s in sessions]
            self.apply_filters()
            self.set_status(f"已载入 {len(self.sessions)} 个会话")
        except Exception as exc:
            self.show_error("读取会话失败", exc)

    def full_text_search(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            messagebox.showinfo("提示", "请先输入要搜索的关键词")
            return
        roles = self.collect_search_roles()
        self.run_worker("search", lambda: self.store.search_messages(query, self.include_archived_var.get(), roles), "正在全文搜索消息正文...")

    def apply_filters(self) -> None:
        q = self.search_var.get().strip().lower()
        mode = {"全部": "all", "活动": "active", "归档": "archived", "文件缺失": "missing"}.get(self.status_filter_var.get(), self.status_filter_var.get())
        result = []
        for s in self.sessions:
            if mode == "active" and s["archived"]:
                continue
            if mode == "archived" and not s["archived"]:
                continue
            if mode == "missing" and s["file_exists"]:
                continue
            haystack = " ".join(str(s.get(k) or "") for k in ("title", "id", "cwd", "preview")).lower()
            if q and q not in haystack:
                continue
            result.append(s)
        self.filtered = result
        valid_ids = {s["id"] for s in result}
        self.selected_ids = {sid for sid in self.selected_ids if sid in valid_ids}
        self.render_tree()

    def render_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for s in self.filtered:
            state = "归档" if s["archived"] else "活动"
            if not s["file_exists"]:
                state = "缺失"
            mark = "√" if s["id"] in self.selected_ids else ""
            title = self.short_text(s["title"], 90)
            if s.get("hit_count_shown"):
                title = f"[命中{s['hit_count_shown']}] {title}"
            self.tree.insert("", END, iid=s["id"], values=(mark, title, iso_to_local_text(s["updated_at"]), state, self.format_bytes(s["file_size"])))
        self.set_status(f"当前列表 {len(self.filtered)} 个，已勾选 {len(self.selected_ids)} 个")

    def on_tree_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.current_id = selection[0]
        session = self.get_current_session()
        if not session:
            return
        self.detail_title.configure(text=session["title"])
        meta = f"ID：{session['id']} | 更新时间：{iso_to_local_text(session['updated_at'])} | 状态：{'归档' if session['archived'] else '活动'} | 文件：{session['rollout_path']}"
        self.detail_meta.configure(text=meta)
        self.run_worker("preview", lambda: self.load_preview(session["id"]))

    def load_preview(self, session_id: str) -> str:
        session = self.store.get_session(session_id)
        if not session:
            return "会话不存在"
        messages = self.store.read_messages(session, limit=180)
        lines = []
        for msg in messages:
            role = {"user": "用户", "assistant": "助手", "developer": "开发者指令", "system": "系统"}.get(msg["role"], msg["role"])
            lines.append(f"[{msg['local_time']}] {role}")
            text = msg.get("text") or ""
            if text:
                lines.append(text)
            if msg.get("image_count"):
                lines.append(f"[图片附件：{msg['image_count']} 个]")
            lines.append("")
        return "\n".join(lines) or "这个会话没有可预览的文本消息。"

    def toggle_current_selection(self, _event=None) -> None:
        if not self.current_id:
            return
        if self.current_id in self.selected_ids:
            self.selected_ids.remove(self.current_id)
        else:
            self.selected_ids.add(self.current_id)
        self.render_tree()

    def select_all_filtered(self) -> None:
        self.selected_ids = {s["id"] for s in self.filtered}
        self.render_tree()

    def clear_selection(self) -> None:
        self.selected_ids.clear()
        self.render_tree()

    def get_current_session(self) -> dict | None:
        return next((s for s in self.sessions if s["id"] == self.current_id), None)

    def archive_current(self, archived: bool) -> None:
        if not self.current_id:
            messagebox.showinfo("提示", "请先选择一个会话")
            return
        self.archive_ids([self.current_id], archived)

    def archive_selected(self, archived: bool) -> None:
        ids = list(self.selected_ids)
        if not ids:
            messagebox.showinfo("提示", "请先勾选会话")
            return
        self.archive_ids(ids, archived)

    def archive_ids(self, ids: list[str], archived: bool) -> None:
        action = "归档" if archived else "恢复"
        if not messagebox.askyesno("确认操作", f"{action}前会自动备份。确定要{action} {len(ids)} 个会话吗？"):
            return
        self.run_worker("refresh", lambda: self.store.archive_sessions(ids, archived), f"正在{action}...")

    def backup_current(self) -> None:
        if not self.current_id:
            messagebox.showinfo("提示", "请先选择一个会话")
            return
        self.run_worker("message", lambda: self.store.create_backup([self.current_id], reason="desktop-current"), "正在备份当前会话...")

    def backup_selected(self) -> None:
        ids = list(self.selected_ids)
        if not ids:
            messagebox.showinfo("提示", "请先勾选会话")
            return
        self.run_worker("message", lambda: self.store.create_backup(ids, reason="desktop-selected"), "正在批量备份...")

    def repair_current(self) -> None:
        if not self.current_id:
            messagebox.showinfo("提示", "请先选择一个会话")
            return
        if not messagebox.askyesno("确认操作", "修复索引会按最后一条消息校正更新时间，执行前会自动备份。继续吗？"):
            return
        self.run_worker("refresh", lambda: self.store.repair_index(self.current_id), "正在修复索引...")

    def export_current(self) -> None:
        if not self.current_id:
            messagebox.showinfo("提示", "请先选择一个会话")
            return
        self.export_ids([self.current_id])

    def export_selected(self) -> None:
        ids = list(self.selected_ids)
        if not ids:
            messagebox.showinfo("提示", "请先勾选会话")
            return
        self.export_ids(ids)

    def export_ids(self, ids: list[str]) -> None:
        fmt = self.export_format_var.get()
        split = self.export_split_var.get()
        include_images = self.export_images_var.get()
        roles = self.collect_export_roles()
        keyword = self.export_keyword_var.get().strip()
        date_from = self.export_date_from_var.get().strip()
        date_to = self.export_date_to_var.get().strip()
        self.run_worker(
            "message",
            lambda: self.store.export_sessions(
                ids,
                fmt=fmt,
                split=split,
                include_images=include_images,
                roles=roles,
                keyword=keyword,
                date_from=date_from,
                date_to=date_to,
            ),
            f"正在导出 {len(ids)} 个会话...",
        )

    def collect_export_roles(self) -> set[str] | None:
        roles = set()
        if self.export_user_var.get():
            roles.add("user")
        if self.export_assistant_var.get():
            roles.add("assistant")
        if self.export_developer_var.get():
            roles.add("developer")
        if self.export_system_var.get():
            roles.add("system")
        return roles or None

    def collect_search_roles(self) -> set[str] | None:
        roles = set()
        if self.search_user_var.get():
            roles.add("user")
        if self.search_assistant_var.get():
            roles.add("assistant")
        if self.search_developer_var.get():
            roles.add("developer")
        if self.search_system_var.get():
            roles.add("system")
        return roles or None

    def start_web_server(self) -> None:
        if self.web_server:
            self.set_status("Web 服务已经启动")
            return
        try:
            port = int(self.web_port_var.get().strip())
            if not (1 <= port <= 65535):
                raise ValueError("端口范围必须是 1-65535")
            ApiHandler.store = self.store
            self.web_server = ThreadingHTTPServer(("127.0.0.1", port), ApiHandler)
            self.web_thread = threading.Thread(target=self.web_server.serve_forever, daemon=True)
            self.web_thread.start()
            self.set_status(f"Web 服务已启动：http://127.0.0.1:{port}")
        except Exception as exc:
            self.web_server = None
            self.show_error("启动 Web 服务失败", exc)

    def open_web_ui(self) -> None:
        port = self.web_port_var.get().strip() or "8765"
        if not self.web_server:
            self.start_web_server()
        webbrowser.open(f"http://127.0.0.1:{port}")

    def stop_web_server(self) -> None:
        if not self.web_server:
            self.set_status("Web 服务未启动")
            return
        server = self.web_server
        self.web_server = None
        threading.Thread(target=server.shutdown, daemon=True).start()
        server.server_close()
        self.set_status("Web 服务已停止")

    def choose_codex_root(self) -> None:
        path = filedialog.askdirectory(title="选择 Codex 数据目录", initialdir=str(self.store.codex_root))
        if not path:
            return
        self.store = CodexStore(Path(path))
        ApiHandler.store = self.store
        self.root_info.configure(text=f"数据目录：{self.store.codex_root}")
        self.current_id = ""
        self.selected_ids.clear()
        self.preview.delete("1.0", END)
        self.refresh_sessions()

    def run_worker(self, kind: str, func, status: str = "正在处理...") -> None:
        self.set_status(status)

        def target() -> None:
            try:
                self.worker_queue.put((kind, func()))
            except Exception as exc:
                self.worker_queue.put(("error", (exc, traceback.format_exc())))

        threading.Thread(target=target, daemon=True).start()

    def _poll_worker(self) -> None:
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "preview":
                    self.preview.delete("1.0", END)
                    self.preview.insert("1.0", str(payload))
                    self.set_status("预览已更新")
                elif kind == "refresh":
                    self.set_status(f"操作完成：{payload}")
                    self.refresh_sessions()
                elif kind == "search":
                    self.sessions = list(payload)
                    self.apply_filters()
                    self.set_status(f"全文搜索完成：命中 {len(self.sessions)} 个会话")
                elif kind == "message":
                    self.set_status(f"操作完成：{payload}")
                    messagebox.showinfo("操作完成", str(payload))
                elif kind == "error":
                    exc, detail = payload
                    self.set_status(str(exc))
                    messagebox.showerror("操作失败", f"{exc}\n\n{detail}")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_worker)

    def show_error(self, title: str, exc: Exception) -> None:
        self.set_status(str(exc))
        messagebox.showerror(title, str(exc))

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    @staticmethod
    def short_text(text: str, limit: int) -> str:
        text = str(text or "")
        return text if len(text) <= limit else text[: limit - 1] + "..."

    @staticmethod
    def format_bytes(bytes_value: int) -> str:
        value = float(bytes_value or 0)
        units = ["B", "KiB", "MiB", "GiB"]
        idx = 0
        while value >= 1024 and idx < len(units) - 1:
            value /= 1024
            idx += 1
        return f"{value:.0f} {units[idx]}" if idx == 0 else f"{value:.2f} {units[idx]}"


def main() -> None:
    root = Tk()
    DesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
