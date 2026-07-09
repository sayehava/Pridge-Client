from __future__ import annotations

import logging
import queue
import tkinter as tk
from logging import Handler, LogRecord
from tkinter import messagebox, ttk

from printbridge_endpoint.config import ClientTokenStore, ConfigStore, EndpointConfig
from printbridge_endpoint.models import JobHistoryEntry
from printbridge_endpoint.printers import Printer, PrinterError, PrinterManager
from printbridge_endpoint.strings import (
    ACTION_REFRESH_PRINTERS,
    ACTION_SAVE,
    ACTION_START,
    ACTION_STOP,
    APP_NAME,
    LABEL_CLIENT_TOKEN,
    LABEL_CONNECTION_STATUS,
    LABEL_HEARTBEAT_INTERVAL,
    LABEL_HEARTBEAT_STATUS,
    LABEL_LOGS,
    LABEL_POLLING_INTERVAL,
    LABEL_PRINTER,
    LABEL_RECENT_JOBS,
    LABEL_SECONDS,
    LABEL_SERVER_URL,
    LABEL_START_AT_LOGIN,
    LABEL_START_ON_LAUNCH,
    MESSAGE_NO_PRINTERS,
    MESSAGE_SETTINGS_SAVED,
    MESSAGE_TOKEN_NOT_DISPLAYED,
    STATUS_STOPPED,
    WINDOW_TITLE,
)
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
        self.worker: PollingWorker | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.printers: list[Printer] = []

        self.server_url_var = tk.StringVar(value=self.config.server_url)
        self.client_token_var = tk.StringVar(value="")
        self.printer_var = tk.StringVar(value=self.config.selected_printer)
        self.polling_interval_var = tk.IntVar(value=self.config.polling_interval_seconds)
        self.heartbeat_interval_var = tk.IntVar(value=self.config.heartbeat_interval_seconds)
        self.start_polling_var = tk.BooleanVar(value=self.config.start_polling_on_launch)
        self.start_at_login_var = tk.BooleanVar(value=self.config.start_at_login)
        self.connection_status_var = tk.StringVar(value=STATUS_STOPPED)
        self.heartbeat_status_var = tk.StringVar(value=STATUS_STOPPED)

        self._configure_root()
        self._build()
        self._install_log_handler()
        self.refresh_printers()
        self.root.after(200, self._drain_events)

        if self.config.start_polling_on_launch:
            self.start_worker()

    def _configure_root(self) -> None:
        self.root.title(WINDOW_TITLE)
        self.root.geometry("920x680")
        self.root.minsize(760, 560)
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(10, 6))
        style.configure("TLabel", padding=(0, 2))
        style.configure("Header.TLabel", font=("TkDefaultFont", 13, "bold"))

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(1, weight=1)

        ttk.Label(main, text=APP_NAME, style="Header.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")

        ttk.Label(main, text=LABEL_SERVER_URL).grid(row=1, column=0, sticky="w", pady=(16, 0))
        ttk.Entry(main, textvariable=self.server_url_var).grid(row=1, column=1, columnspan=3, sticky="ew", pady=(16, 0))

        ttk.Label(main, text=LABEL_CLIENT_TOKEN).grid(row=2, column=0, sticky="w")
        ttk.Entry(main, textvariable=self.client_token_var, show="*").grid(row=2, column=1, columnspan=3, sticky="ew")
        ttk.Label(main, text=MESSAGE_TOKEN_NOT_DISPLAYED).grid(row=3, column=1, columnspan=3, sticky="w")

        ttk.Label(main, text=LABEL_PRINTER).grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.printer_combo = ttk.Combobox(main, textvariable=self.printer_var, state="readonly")
        self.printer_combo.grid(row=4, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(main, text=ACTION_REFRESH_PRINTERS, command=self.refresh_printers).grid(row=4, column=2, sticky="e", padx=(8, 0), pady=(8, 0))

        ttk.Label(main, text=LABEL_POLLING_INTERVAL).grid(row=5, column=0, sticky="w")
        ttk.Spinbox(main, from_=1, to=3600, textvariable=self.polling_interval_var, width=8).grid(row=5, column=1, sticky="w")
        ttk.Label(main, text=LABEL_SECONDS).grid(row=5, column=1, sticky="w", padx=(80, 0))

        ttk.Label(main, text=LABEL_HEARTBEAT_INTERVAL).grid(row=6, column=0, sticky="w")
        ttk.Spinbox(main, from_=5, to=3600, textvariable=self.heartbeat_interval_var, width=8).grid(row=6, column=1, sticky="w")
        ttk.Label(main, text=LABEL_SECONDS).grid(row=6, column=1, sticky="w", padx=(80, 0))

        ttk.Checkbutton(main, text=LABEL_START_ON_LAUNCH, variable=self.start_polling_var).grid(row=7, column=1, sticky="w", pady=(8, 0))
        ttk.Checkbutton(main, text=LABEL_START_AT_LOGIN, variable=self.start_at_login_var).grid(row=8, column=1, sticky="w")

        ttk.Label(main, text=LABEL_CONNECTION_STATUS).grid(row=9, column=0, sticky="w", pady=(14, 0))
        ttk.Label(main, textvariable=self.connection_status_var).grid(row=9, column=1, sticky="w", pady=(14, 0))
        ttk.Label(main, text=LABEL_HEARTBEAT_STATUS).grid(row=10, column=0, sticky="w")
        ttk.Label(main, textvariable=self.heartbeat_status_var).grid(row=10, column=1, sticky="w")

        actions = ttk.Frame(main)
        actions.grid(row=11, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        ttk.Button(actions, text=ACTION_SAVE, command=self.save_settings).pack(side="left")
        ttk.Button(actions, text=ACTION_START, command=self.start_worker).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text=ACTION_STOP, command=self.stop_worker).pack(side="left", padx=(8, 0))

        lower = ttk.PanedWindow(self.root, orient=tk.VERTICAL)
        lower.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))

        jobs_frame = ttk.LabelFrame(lower, text=LABEL_RECENT_JOBS, padding=8)
        jobs_frame.rowconfigure(0, weight=1)
        jobs_frame.columnconfigure(0, weight=1)
        self.jobs = ttk.Treeview(jobs_frame, columns=("status", "detail"), show="headings", height=6)
        self.jobs.heading("status", text="Status")
        self.jobs.heading("detail", text="Detail")
        self.jobs.column("status", width=140, stretch=False)
        self.jobs.column("detail", width=640)
        self.jobs.grid(row=0, column=0, sticky="nsew")
        lower.add(jobs_frame, weight=1)

        logs_frame = ttk.LabelFrame(lower, text=LABEL_LOGS, padding=8)
        logs_frame.rowconfigure(0, weight=1)
        logs_frame.columnconfigure(0, weight=1)
        self.logs = tk.Text(logs_frame, height=12, state="disabled", wrap="word")
        self.logs.grid(row=0, column=0, sticky="nsew")
        lower.add(logs_frame, weight=2)

    def refresh_printers(self) -> None:
        try:
            self.printers = self.printer_manager.list_printers()
        except PrinterError as exc:
            logger.warning("Printer refresh failed: %s", exc)
            self.printers = []

        names = [printer.name for printer in self.printers]
        self.printer_combo["values"] = names
        if names and self.printer_var.get() not in names:
            default = next((printer.name for printer in self.printers if printer.is_default), names[0])
            self.printer_var.set(default)
        if not names:
            self.printer_var.set("")
            self.connection_status_var.set(MESSAGE_NO_PRINTERS)

    def save_settings(self, show_message: bool = True) -> None:
        self.config = self._config_from_form()
        self.config_store.save(self.config)
        token = self.client_token_var.get().strip()
        if token:
            self.token_store.set(token)
            self.client_token_var.set("")
        logger.info(MESSAGE_SETTINGS_SAVED)
        if show_message:
            messagebox.showinfo(WINDOW_TITLE, MESSAGE_SETTINGS_SAVED)

    def start_worker(self) -> None:
        if self.worker and self.worker.state.running:
            return
        self.save_settings(show_message=False)
        token = self.token_store.get()
        self.worker = PollingWorker(
            self.config,
            token,
            printer_manager=self.printer_manager,
            on_status=lambda status: self.events.put(("status", status)),
            on_job=lambda job: self.events.put(("job", job)),
        )
        self.worker.start()

    def stop_worker(self) -> None:
        if self.worker:
            self.worker.stop()
        self.connection_status_var.set(STATUS_STOPPED)

    def _config_from_form(self) -> EndpointConfig:
        try:
            polling_interval = int(self.polling_interval_var.get())
        except (tk.TclError, ValueError):
            polling_interval = self.config.polling_interval_seconds
        try:
            heartbeat_interval = int(self.heartbeat_interval_var.get())
        except (tk.TclError, ValueError):
            heartbeat_interval = self.config.heartbeat_interval_seconds

        config = EndpointConfig(
            server_url=self.server_url_var.get().strip(),
            selected_printer=self.printer_var.get().strip(),
            polling_interval_seconds=max(polling_interval, 1),
            heartbeat_interval_seconds=max(heartbeat_interval, 5),
            start_polling_on_launch=bool(self.start_polling_var.get()),
            start_at_login=bool(self.start_at_login_var.get()),
            logging=self.config.logging,
        )
        return config

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
                self.connection_status_var.set(str(payload))
                if "Heartbeat" in str(payload):
                    self.heartbeat_status_var.set(str(payload))
            elif event == "job" and isinstance(payload, JobHistoryEntry):
                self.jobs.insert("", 0, values=(payload.status, f"{payload.job_id} {payload.detail}".strip()))
            elif event == "log":
                self._append_log(str(payload))
        self.root.after(200, self._drain_events)

    def _append_log(self, line: str) -> None:
        self.logs.configure(state="normal")
        self.logs.insert("end", f"{line}\n")
        self.logs.see("end")
        self.logs.configure(state="disabled")


def run_gui() -> None:
    root = tk.Tk()
    EndpointGui(root)
    root.mainloop()
