"""
Blogger Indexer — single-file Tkinter GUI for Pydroid 3 (Android).

Install once inside Pydroid 3 (menu -> Pip):
    google-auth
    requests

Then just open and run this one file. Everything (key file, history) is
stored next to this script in an "instance" folder it creates automatically.
"""

import os
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import datetime

try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
except ImportError:
    service_account = None
    AuthorizedSession = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
KEY_PATH = os.path.join(INSTANCE_DIR, "service_account.json")
HISTORY_PATH = os.path.join(INSTANCE_DIR, "history.json")
SETTINGS_PATH = os.path.join(INSTANCE_DIR, "settings.json")
os.makedirs(INSTANCE_DIR, exist_ok=True)

SCOPES = [
    "https://www.googleapis.com/auth/indexing",
    "https://www.googleapis.com/auth/webmasters.readonly",
]
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
INSPECT_ENDPOINT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"

ACCENT = "#1F6F5C"
ACCENT_DARK = "#0F4A3C"
GOLD = "#C77D2E"
BG = "#F7F8FA"
INK = "#1B1F27"
INK_SOFT = "#5B6270"
LINE = "#E4E7EC"
SURFACE = "#FFFFFF"
ERR = "#B3261E"


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class IndexerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Blogger Indexer")
        self.root.configure(bg=BG)
        self.session = None
        self.email = None
        self.history = load_json(HISTORY_PATH, [])
        self.settings = load_json(SETTINGS_PATH, {"site_url": ""})

        self._build_style()
        self._build_layout()
        self._try_autoconnect()
        self.root.bind("<Configure>", self._on_resize)

    # ---------------- style ----------------

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        base_font = ("Roboto", 13)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=INK, font=base_font)
        style.configure("Card.TLabel", background=SURFACE, foreground=INK, font=base_font)
        style.configure("Muted.TLabel", background=SURFACE, foreground=INK_SOFT, font=("Roboto", 11))
        style.configure("Head.TLabel", background=BG, foreground=INK, font=("Roboto", 18, "bold"))
        style.configure("Ok.TLabel", background=SURFACE, foreground=ACCENT, font=("Roboto", 11, "bold"))
        style.configure("Err.TLabel", background=SURFACE, foreground=ERR, font=("Roboto", 11, "bold"))
        style.configure("TEntry", font=base_font, padding=8)
        style.configure(
            "Accent.TButton", background=ACCENT, foreground="white",
            font=("Roboto", 12, "bold"), padding=10, borderwidth=0,
        )
        style.map("Accent.TButton", background=[("active", ACCENT_DARK)])
        style.configure(
            "Secondary.TButton", background=SURFACE, foreground=ACCENT,
            font=("Roboto", 12, "bold"), padding=10, borderwidth=1,
        )
        style.map("Secondary.TButton", background=[("active", "#F0F6F4")])
        style.configure("Treeview", font=("Roboto", 10), rowheight=54, background=SURFACE, fieldbackground=SURFACE)
        style.configure("Treeview.Heading", font=("Roboto", 10, "bold"))

    # ---------------- layout ----------------

    def _build_layout(self):
        outer = ttk.Frame(self.root, style="TFrame")
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)

        # Header
        header = ttk.Frame(outer, style="TFrame", padding=(16, 16, 16, 4))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text="Blogger Indexer", style="Head.TLabel").grid(row=0, column=0, sticky="w")
        self.conn_label = ttk.Label(header, text="Not connected", style="TLabel")
        self.conn_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Connect card
        self.connect_card = ttk.Frame(outer, style="Card.TFrame", padding=16)
        self.connect_card.grid(row=1, column=0, sticky="ew", padx=16, pady=8)
        self.connect_card.grid_columnconfigure(0, weight=1)
        ttk.Label(self.connect_card, text="Connect your service account", style="Card.TLabel",
                  font=("Roboto", 14, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(self.connect_card, text="Choose JSON key file", style="Accent.TButton",
                   command=self.pick_key_file).grid(row=1, column=0, sticky="ew", pady=(10, 4))
        ttk.Label(self.connect_card, text="Search Console site URL", style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(8, 2))
        self.site_url_var = tk.StringVar(value=self.settings.get("site_url", ""))
        self.site_entry = ttk.Entry(self.connect_card, textvariable=self.site_url_var)
        self.site_entry.grid(row=3, column=0, sticky="ew")
        self.site_entry.bind("<FocusOut>", lambda e: self._save_site_url())

        # Feed card
        self.feed_card = ttk.Frame(outer, style="Card.TFrame", padding=16)
        self.feed_card.grid(row=2, column=0, sticky="ew", padx=16, pady=8)
        self.feed_card.grid_columnconfigure(0, weight=1)
        ttk.Label(self.feed_card, text="Feed a URL", style="Card.TLabel",
                  font=("Roboto", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(self.feed_card, textvariable=self.url_var)
        self.url_entry.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        self.url_entry.insert(0, "https://freestackhub.blogspot.com/...")

        btn_row = ttk.Frame(self.feed_card, style="Card.TFrame")
        btn_row.grid(row=2, column=0, sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)
        self.push_btn = ttk.Button(btn_row, text="Push for indexing", style="Accent.TButton",
                                    command=self.push_url)
        self.push_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.check_btn = ttk.Button(btn_row, text="Check status", style="Secondary.TButton",
                                     command=self.check_url)
        self.check_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.status_label = ttk.Label(self.feed_card, text="", style="Muted.TLabel", wraplength=320)
        self.status_label.grid(row=3, column=0, sticky="w", pady=(8, 0))

        # History card
        hist_card = ttk.Frame(outer, style="Card.TFrame", padding=16)
        hist_card.grid(row=3, column=0, sticky="nsew", padx=16, pady=(8, 16))
        hist_card.grid_columnconfigure(0, weight=1)
        hist_card.grid_rowconfigure(1, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        ttk.Label(hist_card, text="History", style="Card.TLabel",
                  font=("Roboto", 14, "bold")).grid(row=0, column=0, sticky="w")

        tree_frame = ttk.Frame(hist_card, style="Card.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        cols = ("url", "push", "index")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=6)
        self.tree.heading("url", text="URL")
        self.tree.heading("push", text="Push")
        self.tree.heading("index", text="Index status")
        self.tree.column("url", width=160, anchor="w")
        self.tree.column("push", width=90, anchor="w")
        self.tree.column("index", width=120, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        self._refresh_tree()

    # ---------------- responsive resize ----------------

    def _on_resize(self, event):
        if event.widget != self.root:
            return
        w = event.width
        # Scale wraplength for the status label and tweak column widths on narrow phones.
        self.status_label.configure(wraplength=max(200, w - 60))
        if w < 420:
            self.tree.column("url", width=int(w * 0.45))
            self.tree.column("push", width=int(w * 0.22))
            self.tree.column("index", width=int(w * 0.28))
        else:
            self.tree.column("url", width=int(w * 0.45))
            self.tree.column("push", width=int(w * 0.2))
            self.tree.column("index", width=int(w * 0.25))

    # ---------------- connection ----------------

    def _try_autoconnect(self):
        if os.path.exists(KEY_PATH):
            self._load_credentials()

    def pick_key_file(self):
        path = filedialog.askopenfilename(
            title="Select service account JSON key",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path) as f:
                data = f.read()
            with open(KEY_PATH, "w") as f:
                f.write(data)
        except Exception as e:
            messagebox.showerror("Error", "Couldn't read that file:\n%s" % e)
            return
        self._load_credentials()

    def _load_credentials(self):
        if service_account is None:
            messagebox.showerror(
                "Missing packages",
                "Install 'google-auth' and 'requests' in Pydroid 3's Pip menu first.",
            )
            return
        try:
            creds = service_account.Credentials.from_service_account_file(KEY_PATH, scopes=SCOPES)
            self.session = AuthorizedSession(creds)
            self.email = creds.service_account_email
            self.conn_label.configure(text="Connected: %s" % self.email)
        except Exception as e:
            self.session = None
            self.email = None
            self.conn_label.configure(text="Not connected")
            messagebox.showerror("Error", "That key file couldn't be used:\n%s" % e)

    def _save_site_url(self):
        self.settings["site_url"] = self.site_url_var.get().strip()
        save_json(SETTINGS_PATH, self.settings)

    # ---------------- actions ----------------

    def _get_entry(self, url):
        for h in self.history:
            if h["url"] == url:
                return h
        entry = {"url": url, "pushed_at": None, "push_status": None,
                 "index_verdict": None, "checked_at": None}
        self.history.insert(0, entry)
        return entry

    def push_url(self):
        if not self._require_connected():
            return
        url = self.url_var.get().strip()
        if not url or url.startswith("https://freestackhub.blogspot.com/..."):
            messagebox.showwarning("Missing URL", "Enter the post URL first.")
            return
        self._set_busy(True, "Pushing for indexing...")
        threading.Thread(target=self._push_worker, args=(url,), daemon=True).start()

    def _push_worker(self, url):
        entry = self._get_entry(url)
        try:
            resp = self.session.post(INDEXING_ENDPOINT, json={"url": url, "type": "URL_UPDATED"})
            if resp.status_code == 200:
                entry["push_status"] = "Pushed successfully"
            else:
                err = resp.json().get("error", {}).get("message", resp.text)
                entry["push_status"] = "Error %s: %s" % (resp.status_code, err)
        except Exception as e:
            entry["push_status"] = "Failed: %s" % e
        entry["pushed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.root.after(0, self._after_action, entry)

    def check_url(self):
        if not self._require_connected():
            return
        url = self.url_var.get().strip()
        site_url = self.site_url_var.get().strip()
        if not url or url.startswith("https://freestackhub.blogspot.com/..."):
            messagebox.showwarning("Missing URL", "Enter the post URL first.")
            return
        if not site_url:
            messagebox.showwarning("Missing site URL", "Enter your Search Console site URL first.")
            return
        self._set_busy(True, "Checking index status...")
        threading.Thread(target=self._check_worker, args=(url, site_url), daemon=True).start()

    def _check_worker(self, url, site_url):
        entry = self._get_entry(url)
        try:
            resp = self.session.post(
                INSPECT_ENDPOINT, json={"inspectionUrl": url, "siteUrl": site_url}
            )
            if resp.status_code == 200:
                result = resp.json().get("inspectionResult", {}).get("indexStatusResult", {})
                verdict = result.get("verdict", "UNKNOWN")
                coverage = result.get("coverageState", "")
                entry["index_verdict"] = "%s — %s" % (verdict, coverage) if coverage else verdict
            else:
                err = resp.json().get("error", {}).get("message", resp.text)
                entry["index_verdict"] = "Error %s: %s" % (resp.status_code, err)
        except Exception as e:
            entry["index_verdict"] = "Failed: %s" % e
        entry["checked_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.root.after(0, self._after_action, entry)

    def _after_action(self, entry):
        save_json(HISTORY_PATH, self.history)
        self._refresh_tree()
        self._set_busy(False, entry.get("push_status") or entry.get("index_verdict") or "Done.")

    def _require_connected(self):
        if self.session is None:
            messagebox.showwarning("Not connected", "Choose your service account key file first.")
            return False
        return True

    def _set_busy(self, busy, message=""):
        state = "disabled" if busy else "normal"
        self.push_btn.configure(state=state)
        self.check_btn.configure(state=state)
        self.status_label.configure(text=message)

    # ---------------- history display ----------------

    def _refresh_tree(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for h in self.history:
            short_url = h["url"] if len(h["url"]) <= 40 else h["url"][:37] + "..."
            self.tree.insert("", "end", values=(short_url, h.get("push_status") or "—",
                                                 h.get("index_verdict") or "—"))

    def _on_row_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx < len(self.history):
            self.url_var.set(self.history[idx]["url"])


def main():
    root = tk.Tk()
    # Start reasonably sized; the layout adapts on resize/rotation via <Configure>.
    root.geometry("380x700")
    app = IndexerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
