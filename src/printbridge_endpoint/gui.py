from __future__ import annotations

import logging
import queue
import tkinter as tk
import uuid
from logging import Handler, LogRecord
from tkinter import messagebox

from printbridge_endpoint.autostart import AutoStartError, set_start_at_login
from printbridge_endpoint.config import ClientTokenStore, ConfigStore, EndpointConfig, ServerConfig
from printbridge_endpoint.models import JobHistoryEntry
from printbridge_endpoint.printers import Printer, PrinterError, PrinterManager
from printbridge_endpoint.strings import (
    ACTION_ADD_SERVER,
    ACTION_QUIT,
    ACTION_REFRESH_PRINTERS,
    ACTION_REMOVE_SERVER,
    ACTION_SAVE,
    ACTION_START,
    ACTION_STOP,
    ACTION_UPDATE_SERVER,
    APP_NAME,
    LABEL_CLIENT_TOKEN,
    LABEL_CONNECTION_STATUS,
    LABEL_GLOBAL_SETTINGS,
    LABEL_HEARTBEAT_INTERVAL,
    LABEL_HEARTBEAT_STATUS,
    LABEL_LOGS,
    LABEL_POLLING_INTERVAL,
    LABEL_PRINTER,
    LABEL_RECENT_JOBS,
    LABEL_SECONDS,
    LABEL_SERVER_ENABLED,
    LABEL_SERVER_NAME,
    LABEL_SERVER_PROFILES,
    LABEL_SERVER_URL,
    LABEL_START_AT_LOGIN,
    LABEL_START_ON_LAUNCH,
    MESSAGE_NO_PRINTERS,
    MESSAGE_READY,
    MESSAGE_SERVER_REQUIRED,
    MESSAGE_SETTINGS_SAVED,
    MESSAGE_TOKEN_NOT_DISPLAYED,
    MESSAGE_TRAY_UNAVAILABLE,
    MESSAGE_WINDOW_HIDDEN,
    MESSAGE_WINDOW_MINIMIZED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    WINDOW_TITLE,
)
from printbridge_endpoint.tray import TrayController, TrayUnavailableError
from printbridge_endpoint.worker import PollingWorker


logger = logging.getLogger(__name__)


class QueueLogHandler(Handler):
    def __init__(self, events: queue.Queue[tuple[str, object]]) -> None:
        super().__init__()
        self.events = events

    def emit(self, record: LogRecord) -> None:
        self.events.put(("log", self.format(record)))


class EndpointGui:
    def __init__(
        self,
        root: tk.Tk,
        config_store: ConfigStore | None = None,
        token_store: ClientTokenStore | None = None,
        printer_manager: PrinterManager | None = None,
    ) -> None:
        self.root = root
        self.config_store = config_store or ConfigStore()
        self.token_store = token_store or ClientTokenStore()
        self.printer_manager = printer_manager or PrinterManager()
        self.config = self.config_store.load()
        self.workers: dict[str, PollingWorker] = {}
        self.tray: TrayController | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.printers: list[Printer] = []
        self.selected_server_id = ""

        self.server_name_var = tk.StringVar(value="")
        self.server_url_var = tk.StringVar(value="")
        self.server_enabled_var = tk.BooleanVar(value=True)
        self.client_token_var = tk.StringVar(value="")
        self.printer_var = tk.StringVar(value=self.config.selected_printer)
        self.polling_interval_var = tk.IntVar(value=self.config.polling_interval_seconds)
        self.heartbeat_interval_var = tk.IntVar(value=self.config.heartbeat_interval_seconds)
        self.start_polling_var = tk.BooleanVar(value=self.config.start_polling_on_launch)
        self.start_at_login_var = tk.BooleanVar(value=self.config.start_at_login)
        self.connection_status_var = tk.StringVar(value=STATUS_STOPPED)
        self.heartbeat_status_var = tk.StringVar(value=STATUS_STOPPED)
        self.ready_status_var = tk.StringVar(value=MESSAGE_READY)

        self._configure_root()
        self._build()
        self._install_log_handler()
        self._start_tray()
        self.refresh_printers()
        self.refresh_server_list()
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.lift()
        self.root.after(200, self._drain_events)

        if self.config.start_polling_on_launch:
            self.start_workers()

    def _configure_root(self) -> None:
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1040x720")
        self.root.minsize(920, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.configure(bg="#eef2f7")

    def _build(self) -> None:
        container = tk.Frame(self.root, bg="#eef2f7", padx=18, pady=18)
        container.pack(fill="both", expand=True)

        header = tk.Frame(container, bg="#eef2f7")
        header.pack(fill="x")
        tk.Label(
            header,
            text=APP_NAME,
            bg="#eef2f7",
            fg="#111827",
            font=("Helvetica", 20, "bold"),
        ).pack(side="left")
        tk.Label(
            header,
            textvariable=self.ready_status_var,
            bg="#dbeafe",
            fg="#1d4ed8",
            padx=12,
            pady=5,
        ).pack(side="right")

        body = tk.Frame(container, bg="#eef2f7")
        body.pack(fill="both", expand=True, pady=(16, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(0, weight=1)

        sidebar = self._panel(body, LABEL_SERVER_PROFILES)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        sidebar.rowconfigure(0, weight=1)
        sidebar.columnconfigure(0, weight=1)
        self.server_list = tk.Listbox(sidebar, height=10, activestyle="dotbox", exportselection=False)
        self.server_list.grid(row=0, column=0, sticky="nsew")
        self.server_list.bind("<<ListboxSelect>>", self._on_server_selected)
        server_buttons = tk.Frame(sidebar, bg="#ffffff")
        server_buttons.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._button(server_buttons, ACTION_ADD_SERVER, self.add_server).pack(side="left")
        self._button(server_buttons, ACTION_REMOVE_SERVER, self.remove_server).pack(side="left", padx=(8, 0))

        right = tk.Frame(body, bg="#eef2f7")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        server_panel = self._panel(right, "Server Connection")
        server_panel.grid(row=0, column=0, sticky="ew")
        server_panel.columnconfigure(1, weight=1)
        self._label(server_panel, LABEL_SERVER_NAME).grid(row=0, column=0, sticky="w", pady=4)
        tk.Entry(server_panel, textvariable=self.server_name_var).grid(row=0, column=1, sticky="ew", pady=4)
        tk.Checkbutton(server_panel, text=LABEL_SERVER_ENABLED, variable=self.server_enabled_var, bg="#ffffff").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self._label(server_panel, LABEL_SERVER_URL).grid(row=1, column=0, sticky="w", pady=4)
        tk.Entry(server_panel, textvariable=self.server_url_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        self._label(server_panel, LABEL_CLIENT_TOKEN).grid(row=2, column=0, sticky="w", pady=4)
        tk.Entry(server_panel, textvariable=self.client_token_var, show="*").grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)
        self._hint(server_panel, MESSAGE_TOKEN_NOT_DISPLAYED).grid(row=3, column=1, columnspan=2, sticky="w", pady=(0, 6))
        self._label(server_panel, LABEL_POLLING_INTERVAL).grid(row=4, column=0, sticky="w", pady=4)
        tk.Spinbox(server_panel, from_=1, to=3600, textvariable=self.polling_interval_var, width=8).grid(row=4, column=1, sticky="w", pady=4)
        self._label(server_panel, LABEL_SECONDS).grid(row=4, column=1, sticky="w", padx=(80, 0), pady=4)
        self._label(server_panel, LABEL_HEARTBEAT_INTERVAL).grid(row=5, column=0, sticky="w", pady=4)
        tk.Spinbox(server_panel, from_=5, to=3600, textvariable=self.heartbeat_interval_var, width=8).grid(row=5, column=1, sticky="w", pady=4)
        self._label(server_panel, LABEL_SECONDS).grid(row=5, column=1, sticky="w", padx=(80, 0), pady=4)
        self._button(server_panel, ACTION_UPDATE_SERVER, self.update_selected_server).grid(row=6, column=1, sticky="w", pady=(12, 0))

        global_panel = self._panel(right, LABEL_GLOBAL_SETTINGS)
        global_panel.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        global_panel.columnconfigure(1, weight=1)
        self._label(global_panel, LABEL_PRINTER).grid(row=0, column=0, sticky="w", pady=4)
        self.printer_menu = tk.OptionMenu(global_panel, self.printer_var, "")
        self.printer_menu.configure(bg="#ffffff", anchor="w")
        self.printer_menu.grid(row=0, column=1, sticky="ew", pady=4)
        self._button(global_panel, ACTION_REFRESH_PRINTERS, self.refresh_printers).grid(row=0, column=2, sticky="e", padx=(8, 0), pady=4)
        tk.Checkbutton(global_panel, text=LABEL_START_ON_LAUNCH, variable=self.start_polling_var, bg="#ffffff").grid(row=1, column=1, sticky="w", pady=(8, 0))
        tk.Checkbutton(global_panel, text=LABEL_START_AT_LOGIN, variable=self.start_at_login_var, bg="#ffffff").grid(row=2, column=1, sticky="w")
        self._label(global_panel, LABEL_CONNECTION_STATUS).grid(row=3, column=0, sticky="w", pady=(12, 0))
        self._value(global_panel, self.connection_status_var).grid(row=3, column=1, sticky="w", pady=(12, 0))
        self._label(global_panel, LABEL_HEARTBEAT_STATUS).grid(row=4, column=0, sticky="w", pady=4)
        self._value(global_panel, self.heartbeat_status_var).grid(row=4, column=1, sticky="w", pady=4)
        actions = tk.Frame(global_panel, bg="#ffffff")
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        self._button(actions, ACTION_SAVE, self.save_settings).pack(side="left")
        self._button(actions, ACTION_START, self.start_workers).pack(side="left", padx=(8, 0))
        self._button(actions, ACTION_STOP, self.stop_workers).pack(side="left", padx=(8, 0))
        self._button(actions, ACTION_QUIT, self.quit_application).pack(side="right")

        lower = tk.Frame(right, bg="#eef2f7")
        lower.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        lower.columnconfigure(0, weight=1)
        lower.rowconfigure(0, weight=1)
        lower.rowconfigure(1, weight=2)
        jobs_frame = self._panel(lower, LABEL_RECENT_JOBS)
        jobs_frame.grid(row=0, column=0, sticky="nsew")
        jobs_frame.rowconfigure(0, weight=1)
        jobs_frame.columnconfigure(0, weight=1)
        self.jobs = tk.Listbox(jobs_frame, height=5)
        self.jobs.insert("end", "No jobs yet")
        self.jobs.grid(row=0, column=0, sticky="nsew")
        logs_frame = self._panel(lower, LABEL_LOGS)
        logs_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        logs_frame.rowconfigure(0, weight=1)
        logs_frame.columnconfigure(0, weight=1)
        self.logs = tk.Text(logs_frame, height=10, state="disabled", wrap="word")
        self.logs.grid(row=0, column=0, sticky="nsew")
        self._append_log("PrintBridge Endpoint GUI loaded")

    def refresh_server_list(self) -> None:
        self.server_list.delete(0, "end")
        for server in self.config.servers:
            marker = "on" if server.enabled else "off"
            self.server_list.insert("end", f"[{marker}] {server.name} - {server.server_url}")
        if self.config.servers:
            self.server_list.selection_clear(0, "end")
            self.server_list.selection_set(0)
            self.load_server(self.config.servers[0].id)
        else:
            self.clear_server_form()

    def _on_server_selected(self, _event: object) -> None:
        selection = self.server_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        if 0 <= index < len(self.config.servers):
            self.load_server(self.config.servers[index].id)

    def load_server(self, server_id: str) -> None:
        server = self._server_by_id(server_id)
        if server is None:
            return
        self.selected_server_id = server.id
        self.server_name_var.set(server.name)
        self.server_url_var.set(server.server_url)
        self.server_enabled_var.set(server.enabled)
        self.polling_interval_var.set(server.polling_interval_seconds)
        self.heartbeat_interval_var.set(server.heartbeat_interval_seconds)
        self.client_token_var.set("")

    def clear_server_form(self) -> None:
        self.selected_server_id = ""
        self.server_name_var.set("")
        self.server_url_var.set("")
        self.server_enabled_var.set(True)
        self.polling_interval_var.set(self.config.polling_interval_seconds)
        self.heartbeat_interval_var.set(self.config.heartbeat_interval_seconds)
        self.client_token_var.set("")

    def add_server(self) -> None:
        name = self.server_name_var.get().strip()
        server_url = self.server_url_var.get().strip()
        if not name or not server_url:
            messagebox.showerror(WINDOW_TITLE, MESSAGE_SERVER_REQUIRED)
            return
        server = ServerConfig(
            id=uuid.uuid4().hex,
            name=name,
            server_url=server_url,
            enabled=bool(self.server_enabled_var.get()),
            polling_interval_seconds=self._polling_interval(),
            heartbeat_interval_seconds=self._heartbeat_interval(),
        )
        self.config.servers.append(server)
        token = self.client_token_var.get().strip()
        if token:
            self.token_store.set(token, server.id)
        self.config_store.save(self._config_from_form())
        self.refresh_server_list()
        self.load_server(server.id)

    def update_selected_server(self, show_error: bool = True) -> bool:
        if not self.selected_server_id:
            return False
        server = self._server_by_id(self.selected_server_id)
        if server is None:
            return False
        name = self.server_name_var.get().strip()
        server_url = self.server_url_var.get().strip()
        if not name or not server_url:
            if show_error:
                messagebox.showerror(WINDOW_TITLE, MESSAGE_SERVER_REQUIRED)
            return False
        server.name = name
        server.server_url = server_url
        server.enabled = bool(self.server_enabled_var.get())
        server.polling_interval_seconds = self._polling_interval()
        server.heartbeat_interval_seconds = self._heartbeat_interval()
        token = self.client_token_var.get().strip()
        if token:
            self.token_store.set(token, server.id)
            self.client_token_var.set("")
        self.config_store.save(self._config_from_form())
        self.refresh_server_list()
        self.load_server(server.id)
        return True

    def remove_server(self) -> None:
        if not self.selected_server_id:
            return
        server_id = self.selected_server_id
        self.stop_worker(server_id)
        self.config.servers = [server for server in self.config.servers if server.id != server_id]
        self.token_store.clear(server_id)
        self.config_store.save(self._config_from_form())
        self.refresh_server_list()

    def refresh_printers(self) -> None:
        try:
            self.printers = self.printer_manager.list_printers()
        except PrinterError as exc:
            logger.warning("Printer refresh failed: %s", exc)
            self.printers = []

        names = [printer.name for printer in self.printers]
        menu = self.printer_menu["menu"]
        menu.delete(0, "end")
        for name in names:
            menu.add_command(label=name, command=lambda value=name: self.printer_var.set(value))
        if names and self.printer_var.get() not in names:
            default = next((printer.name for printer in self.printers if printer.is_default), names[0])
            self.printer_var.set(default)
        if not names:
            self.printer_var.set("")
            self.connection_status_var.set(MESSAGE_NO_PRINTERS)

    def save_settings(self, show_message: bool = True) -> None:
        self.update_selected_server(show_error=False)
        self.config = self._config_from_form()
        self.config_store.save(self.config)
        try:
            set_start_at_login(self.config.start_at_login)
        except AutoStartError as exc:
            logger.warning("Could not update auto-start setting: %s", exc)
        logger.info(MESSAGE_SETTINGS_SAVED)
        if show_message:
            messagebox.showinfo(WINDOW_TITLE, MESSAGE_SETTINGS_SAVED)

    def start_workers(self) -> None:
        self.save_settings(show_message=False)
        for server in self.config.servers:
            if server.enabled:
                self.start_worker(server)
        self._update_running_status()

    def start_worker(self, server: ServerConfig) -> None:
        existing = self.workers.get(server.id)
        if existing and existing.state.running:
            return
        runtime_config = self._runtime_config(server)
        worker = PollingWorker(
            runtime_config,
            self.token_store.get(server.id),
            printer_manager=self.printer_manager,
            on_status=lambda status, server_id=server.id, name=server.name: self.events.put(("status", (server_id, name, status))),
            on_job=lambda job, name=server.name: self.events.put(("job", (name, job))),
            on_config=lambda config, server_id=server.id: self.events.put(("config", (server_id, config))),
        )
        self.workers[server.id] = worker
        worker.start()

    def stop_workers(self) -> None:
        for server_id in list(self.workers.keys()):
            self.stop_worker(server_id)
        self._update_running_status()

    def stop_worker(self, server_id: str) -> None:
        worker = self.workers.pop(server_id, None)
        if worker:
            worker.stop()
            worker.join(timeout=5)

    def hide_window(self) -> None:
        if self.tray is None:
            logger.warning(MESSAGE_TRAY_UNAVAILABLE)
            self.root.iconify()
            logger.info(MESSAGE_WINDOW_MINIMIZED)
            return
        logger.info(MESSAGE_WINDOW_HIDDEN)
        self.root.withdraw()

    def show_window(self) -> None:
        self.events.put(("show", None))

    def _show_window_on_main_thread(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_application(self) -> None:
        if self.tray:
            self.tray.stop()
        self.stop_workers()
        self.root.destroy()

    def _start_tray(self) -> None:
        self.tray = TrayController(on_show=self.show_window, on_quit=lambda: self.events.put(("quit", None)))
        try:
            self.tray.start()
        except TrayUnavailableError as exc:
            self.tray = None
            logger.warning("%s %s", MESSAGE_TRAY_UNAVAILABLE, exc)

    def _runtime_config(self, server: ServerConfig) -> EndpointConfig:
        return EndpointConfig(
            server_url=server.server_url,
            servers=[server],
            selected_printer=self.printer_var.get().strip(),
            polling_interval_seconds=server.polling_interval_seconds,
            heartbeat_interval_seconds=server.heartbeat_interval_seconds,
            start_polling_on_launch=bool(self.start_polling_var.get()),
            start_at_login=bool(self.start_at_login_var.get()),
            logging=self.config.logging,
        )

    def _config_from_form(self) -> EndpointConfig:
        return EndpointConfig(
            server_url=self.config.servers[0].server_url if self.config.servers else "",
            servers=self.config.servers,
            selected_printer=self.printer_var.get().strip(),
            polling_interval_seconds=self.config.polling_interval_seconds,
            heartbeat_interval_seconds=self.config.heartbeat_interval_seconds,
            start_polling_on_launch=bool(self.start_polling_var.get()),
            start_at_login=bool(self.start_at_login_var.get()),
            logging=self.config.logging,
        )

    def _polling_interval(self) -> int:
        try:
            return max(int(self.polling_interval_var.get()), 1)
        except (tk.TclError, ValueError):
            return 5

    def _heartbeat_interval(self) -> int:
        try:
            return max(int(self.heartbeat_interval_var.get()), 5)
        except (tk.TclError, ValueError):
            return 30

    def _server_by_id(self, server_id: str) -> ServerConfig | None:
        return next((server for server in self.config.servers if server.id == server_id), None)

    def _install_log_handler(self) -> None:
        handler = QueueLogHandler(self.events)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        logging.getLogger().addHandler(handler)

    def _drain_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "status":
                _server_id, name, status = payload  # type: ignore[misc]
                self.connection_status_var.set(f"{name}: {status}")
                if status == STATUS_RUNNING:
                    self.heartbeat_status_var.set(f"{name}: waiting")
                self._update_running_status()
            elif event == "show":
                self._show_window_on_main_thread()
            elif event == "quit":
                self.quit_application()
            elif event == "job":
                name, job = payload  # type: ignore[misc]
                if isinstance(job, JobHistoryEntry):
                    if self.jobs.size() == 1 and self.jobs.get(0) == "No jobs yet":
                        self.jobs.delete(0)
                    self.jobs.insert(0, f"{name} - {job.status}: {job.job_id} {job.detail}".strip())
            elif event == "config":
                server_id, runtime_config = payload  # type: ignore[misc]
                self._apply_runtime_config(server_id, runtime_config)
            elif event == "log":
                self._append_log(str(payload))
        self.root.after(200, self._drain_events)

    def _apply_runtime_config(self, server_id: str, runtime_config: EndpointConfig) -> None:
        server = self._server_by_id(server_id)
        if server is None:
            return
        server.polling_interval_seconds = runtime_config.polling_interval_seconds
        server.heartbeat_interval_seconds = runtime_config.heartbeat_interval_seconds
        if server_id == self.selected_server_id:
            self.polling_interval_var.set(server.polling_interval_seconds)
            self.heartbeat_interval_var.set(server.heartbeat_interval_seconds)
        self.config_store.save(self._config_from_form())

    def _update_running_status(self) -> None:
        running = sum(1 for worker in self.workers.values() if worker.state.running)
        if running:
            self.ready_status_var.set(f"{running} server(s) running")
            self.connection_status_var.set(f"{running} server(s) running")
        else:
            self.ready_status_var.set(MESSAGE_READY)
            self.connection_status_var.set(STATUS_STOPPED)

    def _append_log(self, line: str) -> None:
        self.logs.configure(state="normal")
        self.logs.insert("end", f"{line}\n")
        self.logs.see("end")
        self.logs.configure(state="disabled")

    def _panel(self, parent: tk.Misc, text: str) -> tk.LabelFrame:
        return tk.LabelFrame(parent, text=text, bg="#ffffff", fg="#111827", padx=12, pady=12, bd=1, relief="solid")

    def _label(self, parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg="#ffffff", fg="#374151", anchor="w")

    def _hint(self, parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg="#ffffff", fg="#6b7280", anchor="w")

    def _value(self, parent: tk.Misc, variable: tk.StringVar) -> tk.Label:
        return tk.Label(parent, textvariable=variable, bg="#ffffff", fg="#111827", anchor="w")

    def _button(self, parent: tk.Misc, text: str, command: object) -> tk.Button:
        return tk.Button(parent, text=text, command=command, padx=12, pady=5)


def run_gui() -> None:
    root = tk.Tk()
    root.endpoint_gui = EndpointGui(root)  # type: ignore[attr-defined]
    root.mainloop()
