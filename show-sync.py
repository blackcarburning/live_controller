#!/usr/bin/env python3
"""
show-sync.py — Standalone show effect editor for show-sync.

Creates and edits show files (JSON) that define a timeline of lighting/display
effects to be played back through the show-sync web client.

Primary media source: `.mov` video files.  Other video/audio formats are also
accepted, but `.mov` is the default filter in the browse dialog and the
recommended workflow.

Usage
-----
    python show-sync.py                  # Start with a blank show
    python show-sync.py myshow.json      # Open an existing show file

Show file format (JSON)
-----------------------
    {
        "version": 1,
        "video": "path/to/show.mov",
        "duration": 180.0,
        "effects": [
            {
                "id": "<hex-id>",
                "type": "solid|fade_in|fade_out|text",
                "start": 0.0,
                "duration": 2.0,
                "params": {"color": "#ff0000", "text": "..."}
            }
        ]
    }

Note: show files saved by older versions of this editor may use the key
``"song"`` instead of ``"video"``.  Both are accepted on load; new files are
always saved with ``"video"``.

Running the show
----------------
    1. Save the show file as myshow.json inside the show-sync/ directory.

    2. Start the show-sync server:
           cd show-sync
           uvicorn app.main:app --host 0.0.0.0 --port 8000

    3. Create a session:
           curl -X POST http://localhost:8000/api/session \\
                -H 'Content-Type: application/json' \\
                -d '{"name": "test"}'

    4. Play the show (replace <id> with the returned session_id):
           curl -X POST "http://localhost:8000/api/session/<id>/play-show?offset=5" \\
                -H 'Content-Type: application/json' \\
                -d @myshow.json

    5. Open http://localhost:8000/join/<id> on each client device.

Effect types
------------
    solid      Fill the screen with a solid color for the duration.
    fade_in    Fade from black to the chosen color over the duration.
    fade_out   Fade from the chosen color back to black over the duration.
    text       Display text centered on screen for the duration.

Testing .mov support
--------------------
    1. Run the editor:
           python show-sync.py

    2. Click "Browse…" next to the Video field — the dialog opens with .mov
       files listed first.

    3. Select your .mov file.  The editor will attempt to read the video
       duration automatically via ffprobe (if installed) and pre-fill the
       Duration field.

    4. Click "▶ Play" to open the video in your system's default player so you
       can reference timestamps while placing effects.

    5. Add effects using the Add/Edit/Delete buttons, setting Start (s) to the
       timestamp in the video where the effect should fire.

    6. Save the show file (File → Save or Ctrl+S).

    7. POST the saved JSON to the play-show endpoint as shown above.  Client
       devices at /join/<id> will receive each effect timed to the video.
"""

import json
import os
import subprocess
import sys
import uuid
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser

_ALLOWED_VIDEO_EXTENSIONS = {
    ".mov", ".mp4", ".mkv", ".avi", ".m4v", ".webm",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
}

EFFECT_TYPES = ["solid", "fade_in", "fade_out", "text"]

DEFAULT_COLOR = "#ff0000"


def _new_id():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Effect edit dialog
# ---------------------------------------------------------------------------

class EffectDialog(tk.Toplevel):
    """Modal dialog for adding or editing a single effect."""

    def __init__(self, parent, effect=None):
        super().__init__(parent)
        self.title("Add Effect" if effect is None else "Edit Effect")
        self.resizable(False, False)
        self.result = None

        e = effect or {}
        self._type_var = tk.StringVar(value=e.get("type", "solid"))
        self._start_var = tk.StringVar(value=str(e.get("start", 0.0)))
        self._dur_var = tk.StringVar(value=str(e.get("duration", 1.0)))
        self._color = e.get("params", {}).get("color", DEFAULT_COLOR)
        self._text_var = tk.StringVar(value=e.get("params", {}).get("text", ""))

        self._build()
        self._update_fields()
        self.grab_set()
        self.wait_window()

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Type:").grid(row=0, column=0, sticky="w", **pad)
        cb = ttk.Combobox(
            frm, textvariable=self._type_var,
            values=EFFECT_TYPES, state="readonly", width=12,
        )
        cb.grid(row=0, column=1, sticky="w", **pad)
        cb.bind("<<ComboboxSelected>>", lambda _: self._update_fields())

        ttk.Label(frm, text="Start (s):").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self._start_var, width=10).grid(
            row=1, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Duration (s):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self._dur_var, width=10).grid(
            row=2, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Color:").grid(row=3, column=0, sticky="w", **pad)
        cf = ttk.Frame(frm)
        cf.grid(row=3, column=1, sticky="w", **pad)
        self._swatch = tk.Label(cf, width=4, bg=self._color, relief="solid")
        self._swatch.pack(side="left")
        ttk.Button(cf, text="Pick…", command=self._pick_color).pack(
            side="left", padx=4)

        self._text_label = ttk.Label(frm, text="Text:")
        self._text_label.grid(row=4, column=0, sticky="w", **pad)
        self._text_entry = ttk.Entry(frm, textvariable=self._text_var, width=28)
        self._text_entry.grid(row=4, column=1, sticky="w", **pad)

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=5, column=0, columnspan=2, pady=(8, 0))
        ttk.Button(btn_frm, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(btn_frm, text="Cancel", command=self.destroy).pack(
            side="left", padx=4)

    def _update_fields(self):
        is_text = self._type_var.get() == "text"
        self._text_entry.config(state="normal" if is_text else "disabled")

    def _pick_color(self):
        result = colorchooser.askcolor(
            color=self._color, parent=self, title="Pick color")
        if result and result[1]:
            self._color = result[1]
            self._swatch.config(bg=self._color)

    def _ok(self):
        try:
            start = float(self._start_var.get())
            duration = float(self._dur_var.get())
        except ValueError:
            messagebox.showerror(
                "Invalid input", "Start and Duration must be numbers.", parent=self)
            return
        if duration <= 0:
            messagebox.showerror(
                "Invalid input", "Duration must be greater than 0.", parent=self)
            return

        params = {"color": self._color}
        if self._type_var.get() == "text":
            params["text"] = self._text_var.get()

        self.result = {
            "type": self._type_var.get(),
            "start": round(start, 3),
            "duration": round(duration, 3),
            "params": params,
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Main editor window
# ---------------------------------------------------------------------------

class ShowEditor(tk.Tk):
    """Main editor window."""

    COLS = ("start", "duration", "type", "color", "text")
    COL_HEADINGS = ("Start (s)", "Duration (s)", "Type", "Color", "Text")

    def __init__(self, filepath=None):
        super().__init__()
        self.title("show-sync editor")
        self.geometry("860x540")
        self._filepath = None
        self._show = self._blank_show()

        self._build_menu()
        self._build_ui()

        if filepath:
            self._load_file(filepath)
        else:
            self._refresh_from_show()

    # --- Data helpers ---

    def _blank_show(self):
        return {"version": 1, "video": "", "duration": 0.0, "effects": []}

    def _sorted_effects(self):
        return sorted(self._show["effects"], key=lambda e: e.get("start", 0))

    # --- Menu ---

    def _build_menu(self):
        mb = tk.Menu(self)
        self.config(menu=mb)

        fm = tk.Menu(mb, tearoff=False)
        mb.add_cascade(label="File", menu=fm)
        fm.add_command(label="New", command=self._new, accelerator="Ctrl+N")
        fm.add_command(label="Open…", command=self._open, accelerator="Ctrl+O")
        fm.add_separator()
        fm.add_command(label="Save", command=self._save, accelerator="Ctrl+S")
        fm.add_command(label="Save As…", command=self._save_as)
        fm.add_separator()
        fm.add_command(label="Quit", command=self.quit)

        self.bind_all("<Control-n>", lambda _: self._new())
        self.bind_all("<Control-o>", lambda _: self._open())
        self.bind_all("<Control-s>", lambda _: self._save())

    # --- UI ---

    def _build_ui(self):
        # Video info
        info_frm = ttk.LabelFrame(self, text="Video", padding=6)
        info_frm.pack(fill="x", padx=8, pady=(8, 0))

        ttk.Label(info_frm, text="File:").grid(row=0, column=0, sticky="w")
        self._video_var = tk.StringVar()
        ttk.Entry(info_frm, textvariable=self._video_var, width=50).grid(
            row=0, column=1, padx=4)
        ttk.Button(info_frm, text="Browse…", command=self._browse_video).grid(
            row=0, column=2)
        ttk.Button(info_frm, text="▶ Play", command=self._play_video).grid(
            row=0, column=3, padx=(4, 0))

        ttk.Label(info_frm, text="Duration (s):").grid(
            row=0, column=4, padx=(12, 4), sticky="w")
        self._dur_var = tk.StringVar()
        ttk.Entry(info_frm, textvariable=self._dur_var, width=8).grid(
            row=0, column=5)

        # Effects list
        list_frm = ttk.LabelFrame(self, text="Effects", padding=6)
        list_frm.pack(fill="both", expand=True, padx=8, pady=8)

        self._tree = ttk.Treeview(
            list_frm, columns=self.COLS, show="headings", selectmode="browse")
        for col, heading in zip(self.COLS, self.COL_HEADINGS):
            self._tree.heading(col, text=heading)
        self._tree.column("start", width=80, anchor="e")
        self._tree.column("duration", width=90, anchor="e")
        self._tree.column("type", width=90)
        self._tree.column("color", width=80)
        self._tree.column("text", width=260)
        self._tree.pack(side="left", fill="both", expand=True)

        vsb = ttk.Scrollbar(list_frm, orient="vertical",
                             command=self._tree.yview)
        vsb.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.bind("<Double-1>", lambda _: self._edit())

        # Buttons
        btn_frm = ttk.Frame(self)
        btn_frm.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Button(btn_frm, text="Add", command=self._add).pack(
            side="left", padx=2)
        ttk.Button(btn_frm, text="Edit", command=self._edit).pack(
            side="left", padx=2)
        ttk.Button(btn_frm, text="Delete", command=self._delete).pack(
            side="left", padx=2)
        ttk.Button(btn_frm, text="Move Up", command=self._move_up).pack(
            side="left", padx=(8, 2))
        ttk.Button(btn_frm, text="Move Down", command=self._move_down).pack(
            side="left", padx=2)

        ttk.Label(btn_frm, text="").pack(side="left", expand=True)
        ttk.Button(btn_frm, text="Save JSON", command=self._save).pack(
            side="right", padx=2)

    # --- List helpers ---

    def _refresh_list(self):
        for row in self._tree.get_children():
            self._tree.delete(row)
        for eff in self._sorted_effects():
            self._tree.insert(
                "", "end", iid=eff["id"],
                values=(
                    eff.get("start", 0),
                    eff.get("duration", 1),
                    eff.get("type", "solid"),
                    eff.get("params", {}).get("color", ""),
                    eff.get("params", {}).get("text", ""),
                ),
            )

    def _refresh_from_show(self):
        # Support both new "video" key and legacy "song" key.
        video_path = self._show.get("video") or self._show.get("song", "")
        self._video_var.set(video_path)
        self._dur_var.set(str(self._show.get("duration", 0.0)))
        self._refresh_list()

    def _selected_effect(self):
        sel = self._tree.selection()
        if not sel:
            return None, None
        eid = sel[0]
        for eff in self._show["effects"]:
            if eff["id"] == eid:
                return eid, eff
        return None, None

    # --- CRUD ---

    def _add(self):
        dlg = EffectDialog(self)
        if dlg.result:
            eff = dlg.result
            eff["id"] = _new_id()
            self._show["effects"].append(eff)
            self._refresh_list()

    def _edit(self):
        eid, eff = self._selected_effect()
        if eff is None:
            messagebox.showinfo("No selection", "Select an effect to edit.")
            return
        dlg = EffectDialog(self, effect=eff)
        if dlg.result:
            eff.update(dlg.result)
            self._refresh_list()

    def _delete(self):
        eid, eff = self._selected_effect()
        if eff is None:
            messagebox.showinfo("No selection", "Select an effect to delete.")
            return
        if messagebox.askyesno("Delete", f"Delete this {eff['type']} effect?"):
            self._show["effects"] = [
                e for e in self._show["effects"] if e["id"] != eid
            ]
            self._refresh_list()

    def _move_up(self):
        sel = self._tree.selection()
        if not sel:
            return
        items = list(self._tree.get_children())
        idx = items.index(sel[0])
        if idx == 0:
            return
        curr = next(e for e in self._show["effects"] if e["id"] == sel[0])
        prev = next(e for e in self._show["effects"] if e["id"] == items[idx - 1])
        curr["start"], prev["start"] = prev["start"], curr["start"]
        self._refresh_list()
        self._tree.selection_set(sel[0])

    def _move_down(self):
        sel = self._tree.selection()
        if not sel:
            return
        items = list(self._tree.get_children())
        idx = items.index(sel[0])
        if idx == len(items) - 1:
            return
        curr = next(e for e in self._show["effects"] if e["id"] == sel[0])
        nxt = next(e for e in self._show["effects"] if e["id"] == items[idx + 1])
        curr["start"], nxt["start"] = nxt["start"], curr["start"]
        self._refresh_list()
        self._tree.selection_set(sel[0])

    # --- File operations ---

    def _collect_show(self):
        """Sync UI fields back into self._show and return it."""
        self._show["video"] = self._video_var.get().strip()
        # Remove legacy "song" key if present so the output is consistent.
        self._show.pop("song", None)
        try:
            self._show["duration"] = float(self._dur_var.get())
        except ValueError:
            self._show["duration"] = 0.0
        return self._show

    def _new(self):
        self._show = self._blank_show()
        self._filepath = None
        self.title("show-sync editor")
        self._refresh_from_show()

    def _open(self):
        path = filedialog.askopenfilename(
            title="Open show file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if "effects" not in data:
                raise ValueError("Not a valid show file (missing 'effects' key)")
            for eff in data["effects"]:
                if "id" not in eff:
                    eff["id"] = _new_id()
            self._show = data
            self._filepath = path
            self.title(f"show-sync editor — {os.path.basename(path)}")
            self._refresh_from_show()
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open file:\n{exc}")

    def _save(self):
        if not self._filepath:
            return self._save_as()
        self._write(self._filepath)

    def _save_as(self):
        path = filedialog.asksaveasfilename(
            title="Save show file",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._filepath = path
            self.title(f"show-sync editor — {os.path.basename(path)}")
            self._write(path)

    def _write(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._collect_show(), f, indent=2)
            print(f"Saved: {path}")
        except Exception as exc:
            messagebox.showerror("Error", f"Could not save file:\n{exc}")

    # --- Misc ---

    def _browse_video(self):
        """Open a file dialog to select the primary video file (.mov preferred)."""
        path = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[
                ("QuickTime / MOV", "*.mov"),
                ("All video files", "*.mov *.mp4 *.mkv *.avi *.m4v *.webm *.m4a"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._video_var.set(path)
            self._try_autofill_duration(path)

    def _play_video(self):
        """Open the selected video file with the system default player."""
        path = self._video_var.get().strip()
        if not path:
            messagebox.showinfo("No video", "Select a video file first.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("File not found", f"Cannot open:\n{path}")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in _ALLOWED_VIDEO_EXTENSIONS:
            messagebox.showerror(
                "Unsupported file",
                f"File extension '{ext}' is not a recognised video/audio format.",
            )
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open video:\n{exc}")

    def _try_autofill_duration(self, path):
        """Attempt to read video duration via ffprobe and pre-fill the field."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format", path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                duration = float(data["format"]["duration"])
                self._dur_var.set(f"{duration:.3f}")
        except Exception:
            # ffprobe not available or failed — user fills in manually.
            pass


def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else None
    editor = ShowEditor(filepath)
    editor.mainloop()


if __name__ == "__main__":
    main()
