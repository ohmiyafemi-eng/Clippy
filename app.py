import base64
import io
import json
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageGrab, ImageTk


DEFAULT_MODEL = "mistral-small-2503"
PRIMARY_KEY_ENV = "FOUNDRY_API_KEY"
SECONDARY_KEY_ENV = "MISTRAL_API_KEY"
PRIMARY_ENDPOINT_ENV = "FOUNDRY_ENDPOINT"
SECONDARY_ENDPOINT_ENV = "MISTRAL_API_ENDPOINT"
HEADER_NAME_ENV = "MISTRAL_API_HEADER"
MODEL_ENV = "MISTRAL_MODEL"

SYSTEM_PROMPT = (
    "You are in an app that revives Microsoft Clippy in Windows. "
    "Speak in a Clippy style. "
    "You are a professional assistant for long-term care pharmacy workflows. "
    "Keep responses short and easy to understand. "
    "If a screenshot includes a P&L and enough financial numbers, perform a comprehensive financial analysis "
    "based on what is provided and summarize the pharmacy's financial performance. Show the summary first. "
    "If a screenshot includes dollar values, respond as the Director of Finance."
)


class Settings:
    def __init__(self) -> None:
        self.endpoint = None
        self.api_key = None
        self.model = None
        self.header = None

    @classmethod
    def load(cls, path: Path) -> "Settings":
        settings = cls()
        if not path.exists():
            return settings
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return settings
        foundry = data.get("Foundry") if isinstance(data, dict) else None
        if isinstance(foundry, dict):
            settings.endpoint = foundry.get("Endpoint")
            settings.api_key = foundry.get("ApiKey")
            settings.model = foundry.get("Model")
            settings.header = foundry.get("Header")
        return settings


def normalize_key(value: str | None) -> str | None:
    if not value:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if trimmed.lower() == "placeholder":
        return None
    return trimmed


def extract_text_from_content(content) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            text = extract_text_from_part(part)
            if text:
                parts.append(text)
        return "".join(parts) if parts else None
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if "content" in content:
            return extract_text_from_content(content.get("content"))
        if "json" in content:
            return json.dumps(content["json"])
        if "parsed" in content:
            return json.dumps(content["parsed"])
    return None


def extract_text_from_part(part) -> str | None:
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        if isinstance(part.get("text"), str):
            return part["text"]
        if "content" in part:
            return extract_text_from_content(part.get("content"))
        if "json" in part:
            return json.dumps(part["json"])
        if "parsed" in part:
            return json.dumps(part["parsed"])
    return None


def extract_content(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    message = choice.get("message") or choice.get("delta") or {}
    content = message.get("content")
    text = extract_text_from_content(content)
    return text or ""


class FoundryClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_api_key(self) -> str:
        key = (
            normalize_key(os.getenv(PRIMARY_KEY_ENV))
            or normalize_key(os.getenv(SECONDARY_KEY_ENV))
            or normalize_key(self.settings.api_key)
        )
        if not key:
            raise RuntimeError("Missing API key. Set FOUNDRY_API_KEY/MISTRAL_API_KEY or update appsettings.json.")
        return key

    def get_endpoint(self) -> str:
        endpoint = os.getenv(PRIMARY_ENDPOINT_ENV) or os.getenv(SECONDARY_ENDPOINT_ENV) or self.settings.endpoint
        if not endpoint:
            raise RuntimeError("Missing endpoint. Set FOUNDRY_ENDPOINT or MISTRAL_API_ENDPOINT.")
        return endpoint.strip()

    def get_header_name(self) -> str:
        return os.getenv(HEADER_NAME_ENV) or self.settings.header or "api-key"

    def get_model(self) -> str:
        return os.getenv(MODEL_ENV) or self.settings.model or DEFAULT_MODEL

    def send_chat(self, messages: list[dict]) -> str:
        payload = {
            "model": self.get_model(),
            "messages": messages,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            self.get_header_name(): self.get_api_key(),
        }
        response = requests.post(self.get_endpoint(), headers=headers, json=payload, timeout=120)
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        return extract_content(data)


class ClippyApp(tk.Tk):
    def __init__(self, client: FoundryClient, avatar_path: Path | None = None) -> None:
        super().__init__()
        self.client = client
        self.title("Clippy (Python)")
        self.geometry("420x640")
        self.configure(bg="#f4f6fb")

        self.bg_color = "#f4f6fb"
        self.assistant_bg = "#ffffff"
        self.user_bg = "#dbe8ff"
        self.assistant_text = "#1f2633"
        self.user_text = "#0f1d36"
        self.avatar_photo = self._load_avatar(avatar_path)
        self.camera_icon = self._build_camera_icon()
        self.token_label = None
        self.message_labels: list[tk.Label] = []

        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.rowconfigure(1, weight=1)

        header = tk.Label(self, text="Clippy", font=("Segoe UI", 16, "bold"), bg=self.bg_color, fg="#2a3345")
        header.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        self.chat_canvas = tk.Canvas(self, bg=self.bg_color, highlightthickness=0)
        self.chat_canvas.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="nsew")

        self.chat_scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.chat_canvas.yview)
        self.chat_scrollbar.grid(row=1, column=1, pady=(0, 8), sticky="ns")
        self.chat_canvas.configure(yscrollcommand=self.chat_scrollbar.set)

        self.messages_frame = tk.Frame(self.chat_canvas, bg=self.bg_color)
        self.canvas_window = self.chat_canvas.create_window((0, 0), window=self.messages_frame, anchor="nw")
        self.messages_frame.bind("<Configure>", self._on_frame_configure)
        self.chat_canvas.bind("<Configure>", self._on_canvas_configure)
        self.chat_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        input_frame = ttk.Frame(self)
        input_frame.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        input_frame.columnconfigure(0, weight=1)
        input_frame.columnconfigure(1, weight=0)

        self.input_var = tk.StringVar()
        self.input_entry = ttk.Entry(input_frame, textvariable=self.input_var)
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.input_entry.bind("<Return>", self._on_send)

        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=0, column=1, sticky="e")

        screenshot_button = ttk.Button(
            button_frame,
            text="Screenshot",
            image=self.camera_icon,
            compound="left",
            command=self._on_screenshot,
        )
        screenshot_button.grid(row=0, column=0, padx=(0, 6))

        send_button = ttk.Button(button_frame, text="Send", command=self._on_send)
        send_button.grid(row=0, column=1)

        status_frame = tk.Frame(self, bg=self.bg_color)
        status_frame.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        self.token_label = tk.Label(
            status_frame,
            text="Tokens (approx): 0",
            font=("Segoe UI", 9),
            bg=self.bg_color,
            fg="#5c667a",
        )
        self.token_label.grid(row=0, column=0, sticky="w")

    def _on_send(self, event=None) -> None:
        prompt = self.input_var.get().strip()
        if not prompt:
            return
        self.input_var.set("")
        self._add_message(prompt, is_user=True)
        self.messages.append({"role": "user", "content": prompt})
        self._update_token_count()
        pending_label = self._add_message("...thinking...", is_user=False)

        thread = threading.Thread(target=self._send_async, args=(pending_label,), daemon=True)
        thread.start()

    def _on_screenshot(self) -> None:
        prompt = self.input_var.get().strip() or "Describe this screenshot."
        self.input_var.set("")

        try:
            image_bytes = self._capture_screenshot()
        except Exception as exc:
            self._add_message(f"Error capturing screenshot: {exc}", is_user=False)
            return

        self._add_message(f"{prompt} (screenshot)", is_user=True)
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": self._to_data_url(image_bytes)}},
        ]
        self.messages.append({"role": "user", "content": content})
        self._update_token_count()
        pending_label = self._add_message("...thinking...", is_user=False)

        thread = threading.Thread(target=self._send_async, args=(pending_label,), daemon=True)
        thread.start()

    def _send_async(self, pending_label: tk.Label) -> None:
        try:
            response = self.client.send_chat(self.messages)
        except Exception as exc:
            response = f"Error: {exc}"
        self.messages.append({"role": "assistant", "content": response})
        self.after(0, self._update_pending_message, pending_label, response)

    def _add_message(self, text: str, is_user: bool) -> tk.Label:
        container = tk.Frame(self.messages_frame, bg=self.bg_color)
        container.pack(fill="x", padx=6, pady=4, anchor="e" if is_user else "w")

        wrap_length = self._get_wrap_length()
        bubble: tk.Label
        if is_user:
            bubble = tk.Label(
                container,
                text=text,
                bg=self.user_bg,
                fg=self.user_text,
                padx=10,
                pady=6,
                wraplength=wrap_length,
                justify="left",
            )
            bubble.pack(anchor="e")
        else:
            row = tk.Frame(container, bg=self.bg_color)
            row.pack(anchor="w")
            if self.avatar_photo is not None:
                avatar = tk.Label(row, image=self.avatar_photo, bg=self.bg_color)
                avatar.pack(side="left", padx=(0, 6))
            bubble = tk.Label(
                row,
                text=text,
                bg=self.assistant_bg,
                fg=self.assistant_text,
                padx=10,
                pady=6,
                wraplength=wrap_length,
                justify="left",
            )
            bubble.pack(side="left", anchor="w")

        self.message_labels.append(bubble)
        self._refresh_wrap_lengths()
        self._scroll_to_bottom()
        return bubble

    def _update_pending_message(self, label: tk.Label, response: str) -> None:
        label.configure(text=response)
        self._update_token_count()
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        self.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    def _get_wrap_length(self) -> int:
        width = max(self.winfo_width(), 420)
        return max(220, width - 160)

    def _refresh_wrap_lengths(self) -> None:
        wrap_length = self._get_wrap_length()
        for label in self.message_labels:
            label.configure(wraplength=wrap_length)

    def _on_frame_configure(self, event) -> None:
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.chat_canvas.itemconfigure(self.canvas_window, width=event.width)
        self._refresh_wrap_lengths()

    def _on_mousewheel(self, event) -> None:
        if event.delta:
            self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _capture_screenshot(self) -> bytes:
        bbox = self._get_current_monitor_bbox()
        was_visible = self.state() != "withdrawn"
        if was_visible:
            self.withdraw()
            self.update_idletasks()
        try:
            if bbox is None:
                image = ImageGrab.grab()
            else:
                image = ImageGrab.grab(bbox=bbox, all_screens=True)
        finally:
            if was_visible:
                self.deiconify()
                self.update_idletasks()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _get_current_monitor_bbox(self) -> tuple[int, int, int, int] | None:
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            monitor_from_point = ctypes.windll.user32.MonitorFromPoint
            monitor_from_window = ctypes.windll.user32.MonitorFromWindow
            get_monitor_info = ctypes.windll.user32.GetMonitorInfoW
            monitor_from_point.argtypes = [wintypes.POINT, wintypes.DWORD]
            monitor_from_point.restype = wintypes.HMONITOR
            monitor_from_window.argtypes = [wintypes.HWND, wintypes.DWORD]
            monitor_from_window.restype = wintypes.HMONITOR
            get_monitor_info.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
            get_monitor_info.restype = wintypes.BOOL

            hwnd = wintypes.HWND(self.winfo_id())
            monitor = monitor_from_window(hwnd, 2)
            if not monitor:
                x = self.winfo_rootx() + self.winfo_width() // 2
                y = self.winfo_rooty() + self.winfo_height() // 2
                point = wintypes.POINT(x, y)
                monitor = monitor_from_point(point, 2)
            if not monitor:
                return None
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if not get_monitor_info(monitor, ctypes.byref(info)):
                return None
            return (info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom)
        except Exception:
            return None

    def _to_data_url(self, image_bytes: bytes) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _estimate_tokens(self) -> int:
        total_chars = 0
        for message in self.messages:
            content = message.get("content")
            total_chars += self._count_content_chars(content)
        return max(1, total_chars // 4)

    def _count_content_chars(self, content) -> int:
        if content is None:
            return 0
        if isinstance(content, str):
            return len(content)
        if isinstance(content, list):
            return sum(self._count_content_chars(part) for part in content)
        if isinstance(content, dict):
            if "text" in content:
                return len(str(content.get("text") or ""))
            if "content" in content:
                return self._count_content_chars(content.get("content"))
            if "url" in content:
                return 0
        return len(str(content))

    def _update_token_count(self) -> None:
        if self.token_label is None:
            return
        approx_tokens = self._estimate_tokens()
        self.token_label.configure(text=f"Tokens (approx): {approx_tokens}")

    def _load_avatar(self, path: Path | None) -> ImageTk.PhotoImage | None:
        if path is None or not path.exists():
            return None
        try:
            image = Image.open(path).convert("RGBA")
            image.thumbnail((40, 40))
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def _build_camera_icon(self) -> ImageTk.PhotoImage:
        size = 18
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        body = (2, 5, size - 2, size - 3)
        draw.rounded_rectangle(body, radius=3, fill="#2f3b52")
        draw.rectangle((6, 2, size - 6, 5), fill="#2f3b52")
        draw.ellipse((6, 7, size - 6, size - 7), outline="#ffffff", width=2)
        return ImageTk.PhotoImage(image)


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    load_dotenv(base_dir / ".env", override=False)
    appsettings = base_dir.parent / "Clippy" / "appsettings.json"
    settings = Settings.load(appsettings)
    client = FoundryClient(settings)

    avatar_path = base_dir.parent / "Clippy" / "Assets" / "Clippy" / "Clippy.png"
    app = ClippyApp(client, avatar_path=avatar_path)
    app.mainloop()


if __name__ == "__main__":
    main()
