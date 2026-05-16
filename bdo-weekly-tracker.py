import tkinter as tk
from tkinter import messagebox
import json, os, sys, time, threading, webbrowser
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen
from urllib.error import URLError

# ── Version ──────────────────────────────────────────────────────────────────
APP_VERSION     = "1.0.0"
VERSION_URL     = "https://gist.githubusercontent.com/StormProgramming/8101519cb57aa8d3d974cc9bcad7063f/raw/version.json"
RELEASES_URL    = "https://github.com/StormProgramming/bdo-weekly-tracker/releases/latest"

# ── Data path ────────────────────────────────────────────────────────────────
def get_data_path():
    base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "BDOTracker")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "bdo_tracker_data.json")

DATA_FILE = get_data_path()

# ── Time helpers (system local time, resets anchored to UTC) ─────────────────
def now_local():
    """Current time in the system's local timezone."""
    return datetime.now().astimezone()

def tz_abbr():
    """Short timezone label e.g. BST, EST, CET for display."""
    return datetime.now().astimezone().strftime("%Z")

def reset_local_label(weekday):
    """Returns a human-readable local time string for when a weekday reset fires.
    e.g. 'Sunday 02:00 CEST' or 'Sunday 01:00 BST' depending on the user's OS timezone."""
    SERVER_TZ = timezone(timedelta(hours=1))
    now_server = datetime.now(SERVER_TZ)
    days_ahead = (weekday - now_server.weekday()) % 7
    if days_ahead == 0:
        cand = now_server.replace(hour=1, minute=0, second=0, microsecond=0)
        if now_server >= cand:
            days_ahead = 7
    reset_server = (now_server + timedelta(days=days_ahead)).replace(
        hour=1, minute=0, second=0, microsecond=0)
    reset_local = reset_server.astimezone()
    return reset_local.strftime(f"%A %H:%M {tz_abbr()}")

def next_weekday_1am(weekday):
    """
    Returns UTC timestamp of the next occurrence of `weekday` at 01:00 BST (UTC+1).
    The game resets are fixed game-server times, not local times.
    BST = UTC+1 always for reset purposes (game server timezone).
    """
    SERVER_TZ = timezone(timedelta(hours=1))  # BDO EU server is BST/UTC+1
    now_server = datetime.now(SERVER_TZ)
    days_ahead = (weekday - now_server.weekday()) % 7
    if days_ahead == 0:
        cand = now_server.replace(hour=1, minute=0, second=0, microsecond=0)
        if now_server >= cand:
            days_ahead = 7
    reset_server = (now_server + timedelta(days=days_ahead)).replace(
        hour=1, minute=0, second=0, microsecond=0)
    return reset_server.timestamp()

def get_reset_ts(reset_type, completed_at=None):
    if reset_type == "sunday":   return next_weekday_1am(6)
    if reset_type == "thursday": return next_weekday_1am(3)
    if reset_type == "5day":     return (completed_at or time.time()) + 5 * 86400
    return time.time() + 86400

def fmt_delta(secs):
    if secs <= 0: return "Ready"
    s = int(secs)
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return f"{d}d {h:02d}h {m:02d}m" if d else f"{h:02d}h {m:02d}m {s:02d}s"

# ── Persistence ──────────────────────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}

def save_data(d):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(d, f, indent=2)
    except Exception as e:
        print(e)

# ── Default activities ───────────────────────────────────────────────────────
DEFAULTS = [
    {"name": "Black Shrine (Solo)",   "reset_type": "sunday"},
    {"name": "Black Shrine (Party)",  "reset_type": "sunday"},
    {"name": "Altar of Blood",        "reset_type": "sunday"},
    {"name": "Pit of the Undying",    "reset_type": "thursday"},
    {"name": "Red Heart",             "reset_type": "thursday"},
    {"name": "Guild Bosses",          "reset_type": "thursday"},
    {"name": "Edania Bosses",         "reset_type": "thursday"},
    {"name": "Atoraxxion Dungeons",   "reset_type": "thursday"},
    {"name": "Dark Rifts",            "reset_type": "5day"},
]

# ── Palette ──────────────────────────────────────────────────────────────────
BG         = "#0e0e16"
SURFACE    = "#16161f"
SURFACE2   = "#1c1c28"
BORDER     = "#252535"
GOLD       = "#d4a843"
PURPLE     = "#7c5cbf"
RED        = "#c0414a"
GREEN      = "#3eb87a"
GREEN_DIM  = "#132b1e"
TEXT       = "#ddd8cc"
TEXT_MID   = "#8a8799"
TEXT_DIM   = "#4a4760"
WHITE      = "#f0ece4"

BADGE = {
    "sunday":   (RED,    "#2e1018"),
    "thursday": (PURPLE, "#1a1030"),
    "5day":     (GOLD,   "#2a1e08"),
}

# ── Fonts ────────────────────────────────────────────────────────────────────
F_TITLE  = ("Segoe UI", 15, "bold")
F_HEAD   = ("Segoe UI",  8, "bold")
F_BODY   = ("Segoe UI", 11)
F_BOLD   = ("Segoe UI", 11, "bold")
F_SMALL  = ("Segoe UI",  9)
F_BADGE  = ("Segoe UI",  8, "bold")
F_MONO   = ("Consolas",  9)
F_CLOCK  = ("Consolas", 11)

# ─────────────────────────────────────────────────────────────────────────────
class BDOTracker:
    def __init__(self, root):
        self.root = root
        self.root.title("BDO Weekly Tracker")
        self.root.configure(bg=BG)
        self.root.minsize(720, 420)

        self.data       = load_data()
        self.activities = self._build_acts()
        self.row_refs   = {}

        self._build_ui()
        self._restore_geometry()
        self.root.bind("<Configure>", self._on_configure)
        self._tick()
        # Check for updates in background so it never blocks startup
        threading.Thread(target=self._check_for_update, daemon=True).start()

    def _check_for_update(self):
        try:
            with urlopen(VERSION_URL, timeout=5) as r:
                data = json.loads(r.read().decode())
            latest = data.get("version", "")
            if latest and latest != APP_VERSION:
                # Schedule the popup on the main thread
                self.root.after(0, lambda: self._show_update_dialog(latest))
        except Exception:
            pass  # Silently ignore — no internet, server down, etc.

    def _show_update_dialog(self, latest):
        msg = (
            "A new version of BDO Weekly Tracker is available!\n\n"
            f"  Current:  v{APP_VERSION}\n"
            f"  Latest:   v{latest}\n\n"
            "Open the download page?"
        )
        if messagebox.askyesno("Update Available", msg):
            webbrowser.open(RELEASES_URL)

    def _restore_geometry(self):
        geom = self.data.get("_window_geometry")
        if geom:
            try:
                self.root.geometry(geom)
            except Exception:
                pass

    def _on_configure(self, event):
        # Only save if it's the root window being resized/moved
        if event.widget is self.root:
            self._pending_geometry = self.root.geometry()

    def _build_acts(self):
        hidden = self.data.get("_hidden_defaults", [])
        acts = [a for a in DEFAULTS if a["name"] not in hidden]
        for c in self.data.get("_custom", []):
            if not any(a["name"] == c["name"] for a in acts):
                acts.append(c)
        return acts

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self.root, bg=SURFACE)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=GOLD, height=3).pack(fill="x")

        inner = tk.Frame(hdr, bg=SURFACE, padx=24, pady=14)
        inner.pack(fill="x")

        left = tk.Frame(inner, bg=SURFACE)
        left.pack(side="left")
        tk.Label(left, text="BDO  WEEKLY  TRACKER", font=F_TITLE,
                 bg=SURFACE, fg=WHITE).pack(anchor="w")
        self.subtitle_var = tk.StringVar()
        tk.Label(left, textvariable=self.subtitle_var, font=F_SMALL,
                 bg=SURFACE, fg=TEXT_MID).pack(anchor="w", pady=(2,0))
        tk.Label(left, text="made by Storm", font=("Segoe UI", 7),
                 bg=SURFACE, fg=TEXT_DIM).pack(anchor="w", pady=(2,0))

        right = tk.Frame(inner, bg=SURFACE)
        right.pack(side="right")
        self.clock_var = tk.StringVar()
        tk.Label(right, textvariable=self.clock_var, font=F_CLOCK,
                 bg=SURFACE, fg=GOLD).pack(anchor="e")
        self.date_var = tk.StringVar()
        tk.Label(right, textvariable=self.date_var, font=F_SMALL,
                 bg=SURFACE, fg=TEXT_DIM).pack(anchor="e", pady=(2,0))

        tk.Frame(hdr, bg=BORDER, height=1).pack(fill="x")

        # ── Legend ──
        leg = tk.Frame(self.root, bg=BG, padx=24, pady=7)
        leg.pack(fill="x")
        for rtype, label in [("sunday",   reset_local_label(6)),
                              ("thursday", reset_local_label(3)),
                              ("5day",     "5 Days After Kill")]:
            fg, _ = BADGE[rtype]
            f = tk.Frame(leg, bg=BG)
            f.pack(side="left", padx=(0,22))
            tk.Label(f, text="⬤", font=("Segoe UI",7), bg=BG, fg=fg).pack(side="left")
            tk.Label(f, text=f"  {label}", font=("Segoe UI",8), bg=BG, fg=TEXT_DIM).pack(side="left")

        # ── Column headers ──
        col_hdr = tk.Frame(self.root, bg=SURFACE2, padx=24, pady=5)
        col_hdr.pack(fill="x")
        tk.Label(col_hdr, text="ACTIVITY", font=F_HEAD, bg=SURFACE2,
                 fg=TEXT_DIM, anchor="w", width=30).pack(side="left")
        tk.Label(col_hdr, text="RESET", font=F_HEAD, bg=SURFACE2,
                 fg=TEXT_DIM, anchor="w", width=13).pack(side="left")
        tk.Label(col_hdr, text="RESETS IN", font=F_HEAD, bg=SURFACE2,
                 fg=TEXT_DIM, anchor="w", width=18).pack(side="left")
        tk.Label(col_hdr, text="DEL", font=F_HEAD, bg=SURFACE2,
                 fg=TEXT_DIM, anchor="center", width=6).pack(side="right", padx=(0,6))
        tk.Label(col_hdr, text="DONE", font=F_HEAD, bg=SURFACE2,
                 fg=TEXT_DIM, anchor="center", width=6).pack(side="right", padx=(0,4))
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        # ── Scrollable list ──
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview,
                          bg=SURFACE2, troughcolor=BG, activebackground=BORDER,
                          width=10)
        sb.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=sb.set)

        self.rows_frame = tk.Frame(self.canvas, bg=BG)
        self._cwin = self.canvas.create_window((0,0), window=self.rows_frame, anchor="nw")

        self.rows_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._cwin, width=e.width))
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # ── Footer ──
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")
        foot = tk.Frame(self.root, bg=SURFACE, padx=20, pady=9)
        foot.pack(fill="x")

        self._btn(foot, "＋  Add Weekly",      self._add_custom,       GOLD,   "#000").pack(side="left")
        self._btn(foot, "↩  Restore Defaults", self._restore_defaults, PURPLE, WHITE).pack(side="left", padx=(8,0))
        self._btn(foot, "↺  Reset All",        self._reset_all,        RED,    WHITE).pack(side="right")

        self.status_var = tk.StringVar()
        tk.Label(foot, textvariable=self.status_var, font=F_SMALL,
                 bg=SURFACE, fg=TEXT_MID).pack(side="right", padx=16)

        self._render_rows()

    def _btn(self, parent, text, cmd, fg, bg_text):
        b = tk.Label(parent, text=text, font=("Segoe UI",9,"bold"),
                     bg=SURFACE2, fg=fg, padx=14, pady=6, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>",    lambda e: b.config(bg=BORDER))
        b.bind("<Leave>",    lambda e: b.config(bg=SURFACE2))
        return b

    # ── Row rendering ─────────────────────────────────────────────────────────
    def _render_rows(self):
        for w in self.rows_frame.winfo_children():
            w.destroy()
        self.row_refs = {}

        GROUP_LABELS = {
            "sunday":   (f"SUN RESETS  ——  {reset_local_label(6)}", RED),
            "thursday": (f"THU RESETS  ——  {reset_local_label(3)}", PURPLE),
            "5day":     ("5-DAY RESETS  ——  5 Days After Kill", GOLD),
        }
        seen_groups = set()
        row_idx = 0  # track visual alternating index within each group

        for act in self.activities:
            rtype = act["reset_type"]
            if rtype not in seen_groups:
                seen_groups.add(rtype)
                label, fg = GROUP_LABELS.get(rtype, ("CUSTOM", TEXT_DIM))
                # Spacer before group (except the first)
                if seen_groups != {rtype}:
                    tk.Frame(self.rows_frame, bg=BG, height=6).pack(fill="x")
                hdr = tk.Frame(self.rows_frame, bg=SURFACE2, padx=24, pady=4)
                hdr.pack(fill="x")
                tk.Label(hdr, text=label, font=("Segoe UI", 7, "bold"),
                         bg=SURFACE2, fg=fg).pack(side="left")
                tk.Frame(self.rows_frame, bg=BORDER, height=1).pack(fill="x")
                row_idx = 0

            self._make_row(row_idx, act)
            row_idx += 1

        self._update_status()

    def _make_row(self, idx, act):
        name   = act["name"]
        rtype  = act["reset_type"]
        state  = self.data.get(name, {})
        done   = state.get("done", False)
        custom = not any(a["name"] == name for a in DEFAULTS)

        rbg   = GREEN_DIM if done else (SURFACE if idx % 2 == 0 else BG)
        nfg   = GREEN     if done else WHITE
        hovbg = "#1a2e22" if done else "#1e1e2e"

        row = tk.Frame(self.rows_frame, bg=rbg, pady=9)
        row.pack(fill="x")
        tk.Frame(self.rows_frame, bg=BORDER, height=1).pack(fill="x")

        # ── RIGHT side: pack these first so left side fills remaining space ──

        # Delete — rightmost.
        dlbl = tk.Label(row, text="✕", font=("Segoe UI", 10, "bold"),
                        bg=SURFACE2, fg=TEXT_DIM, width=4, anchor="center",
                        cursor="hand2", padx=4, pady=4)
        dlbl.pack(side="right", padx=(4, 20))
        dlbl.bind("<Button-1>", lambda e, n=name: self._delete_activity(n))
        dlbl.bind("<Enter>",    lambda e, w=dlbl: w.config(fg=RED,      bg="#2a1015"))
        dlbl.bind("<Leave>",    lambda e, w=dlbl: w.config(fg=TEXT_DIM, bg=SURFACE2))

        # Checkbox — left of delete. Always same font/width. Colours only change.
        chk_fg = "#0a0a10" if done else TEXT_DIM
        chk_bg = GREEN     if done else SURFACE2
        chk = tk.Label(row, text="✔", font=("Segoe UI", 10, "bold"),
                       bg=chk_bg, fg=chk_fg, width=4, anchor="center",
                       cursor="hand2", padx=4, pady=4)
        chk.pack(side="right", padx=(0, 4))
        chk.bind("<Button-1>", lambda e, n=name: self._toggle(n))

        # ── LEFT side ──
        nlbl = tk.Label(row, text=name, font=F_BODY,
                        bg=rbg, fg=nfg, anchor="w", width=28)
        nlbl.pack(side="left", padx=(20, 0))

        bfg, bbg = BADGE.get(rtype, (TEXT_DIM, SURFACE2))
        btxt = {"sunday":"● SUN","thursday":"● THU","5day":"● 5-DAY"}.get(rtype, "● CUSTOM")
        blbl = tk.Label(row, text=btxt, font=F_BADGE,
                        bg=bbg, fg=bfg, padx=8, pady=3, width=10, anchor="w")
        blbl.pack(side="left", padx=(0, 12))

        cdlbl = tk.Label(row, text=self._get_cd(name, rtype, state), font=F_MONO,
                         bg=rbg, fg=GREEN if done else TEXT_MID, anchor="w", width=20)
        cdlbl.pack(side="left")

        # Toggle on row bg, name, countdown
        for w in [row, nlbl, cdlbl]:
            w.bind("<Button-1>", lambda e, n=name: self._toggle(n))

        # Hover — only the row-coloured widgets
        hover_ws = [row, nlbl, cdlbl]
        for w in hover_ws:
            w.bind("<Enter>", lambda e, ws=hover_ws, hb=hovbg: [x.config(bg=hb) for x in ws])
            w.bind("<Leave>", lambda e, ws=hover_ws, ob=rbg:   [x.config(bg=ob)  for x in ws])

        self.row_refs[name] = cdlbl

        # completed_at stored in JSON for future use but not displayed

    def _get_cd(self, name, rtype, state):
        done = state.get("done", False)
        if done:
            rem = state.get("reset_at", 0) - time.time()
            return f"Completed  {fmt_delta(rem)}" if rem > 0 else "Ready to reset"
        # 5-day timer only makes sense after a kill — show nothing when not done
        if rtype == "5day":
            return "No recent kill"
        if rtype == "sunday":    ts = next_weekday_1am(6)
        elif rtype == "thursday": ts = next_weekday_1am(3)
        else: return ""
        return fmt_delta(ts - time.time())

    # ── Toggle ────────────────────────────────────────────────────────────────
    def _toggle(self, name):
        act = next((a for a in self.activities if a["name"] == name), None)
        if not act: return
        state = self.data.get(name, {})
        if state.get("done"):
            self.data[name] = {"done": False}
        else:
            now_ts = time.time()
            self.data[name] = {"done": True, "completed_at": now_ts,
                               "reset_at": get_reset_ts(act["reset_type"], now_ts)}
        save_data(self.data)
        self._render_rows()

    # ── Auto-reset ────────────────────────────────────────────────────────────
    # save_data only fires when a reset actually triggers — not every tick
    def _check_resets(self):
        changed = False
        for act in self.activities:
            state = self.data.get(act["name"], {})
            if state.get("done") and time.time() >= state.get("reset_at", 0):
                self.data[act["name"]] = {"done": False}
                changed = True
        if changed:
            save_data(self.data)
        return changed

    # ── Tick — only update countdown labels in-place, never full re-render ────
    def _tick(self):
        n = now_local()
        self.clock_var.set(n.strftime(f"%H:%M:%S  {tz_abbr()}"))
        self.date_var.set(n.strftime("%A, %d %B %Y"))

        if self._check_resets():
            self._render_rows()
        else:
            for act in self.activities:
                name = act["name"]
                lbl  = self.row_refs.get(name)
                if lbl:
                    try:
                        lbl.config(text=self._get_cd(name, act["reset_type"],
                                                     self.data.get(name, {})))
                    except tk.TclError:
                        pass

        self._update_status()
        self._save_geometry_if_pending()
        self.root.after(1000, self._tick)

    # ── Geometry persistence ─────────────────────────────────────────────────
    def _save_geometry_if_pending(self):
        geom = getattr(self, "_pending_geometry", None)
        if geom and geom != self.data.get("_window_geometry"):
            self.data["_window_geometry"] = geom
            save_data(self.data)
            self._pending_geometry = None

    # ── Status ────────────────────────────────────────────────────────────────
    def _update_status(self):
        done  = sum(1 for a in self.activities if self.data.get(a["name"], {}).get("done"))
        total = len(self.activities)
        pct   = int(done/total*100) if total else 0
        self.status_var.set(f"{done}/{total}  ({pct}%)")
        self.subtitle_var.set(f"{done} of {total} weeklies completed this week")

    # ── Add custom ────────────────────────────────────────────────────────────
    def _add_custom(self):
        dlg = CustomDialog(self.root)
        self.root.wait_window(dlg.top)
        if not dlg.result: return
        name, rtype = dlg.result
        if any(a["name"] == name for a in self.activities):
            messagebox.showwarning("Duplicate", f'"{name}" already exists.')
            return
        act = {"name": name, "reset_type": rtype}
        self.activities.append(act)
        customs = self.data.get("_custom", [])
        customs.append(act)
        self.data["_custom"] = customs
        save_data(self.data)
        self._render_rows()

    # ── Delete any activity (default or custom) ─────────────────────────────
    def _delete_activity(self, name):
        is_default = any(a["name"] == name for a in DEFAULTS)
        note = "\n\nThis is a default weekly. It won't return unless you clear your save data." if is_default else ""
        if not messagebox.askyesno("Remove Activity", f'Remove "{name}"?{note}'): return
        self.activities = [a for a in self.activities if a["name"] != name]
        hidden = self.data.get("_hidden_defaults", [])
        if is_default and name not in hidden:
            hidden.append(name)
        self.data["_hidden_defaults"] = hidden
        self.data["_custom"] = [c for c in self.data.get("_custom", []) if c["name"] != name]
        self.data.pop(name, None)
        save_data(self.data)
        self._render_rows()

    # ── Restore hidden defaults ──────────────────────────────────────────────
    def _restore_defaults(self):
        hidden = self.data.get("_hidden_defaults", [])
        if not hidden:
            messagebox.showinfo("Nothing to Restore", "No default weeklies have been removed.")
            return
        nl = "\n"
        names = nl.join(f"  • {n}" for n in hidden)
        if not messagebox.askyesno("Restore Defaults", f"Restore these default weeklies?{nl}{nl}{names}"):
            return
        self.data["_hidden_defaults"] = []
        save_data(self.data)
        self.activities = self._build_acts()
        self._render_rows()

    # ── Reset all ─────────────────────────────────────────────────────────────
    def _reset_all(self):
        if not messagebox.askyesno("Reset All", "Mark all activities as incomplete?"): return
        for act in self.activities:
            self.data[act["name"]] = {"done": False}
        save_data(self.data)
        self._render_rows()


# ── Add Custom Dialog ─────────────────────────────────────────────────────────
class CustomDialog:
    def __init__(self, parent):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("Add Custom Weekly")
        self.top.configure(bg=BG)
        self.top.resizable(False, False)
        self.top.grab_set()
        self.top.geometry("380x265")

        tk.Frame(self.top, bg=GOLD, height=3).pack(fill="x")

        body = tk.Frame(self.top, bg=BG, padx=28, pady=20)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="ACTIVITY NAME", font=F_HEAD, bg=BG, fg=TEXT_DIM).pack(anchor="w")
        self.name_var = tk.StringVar()
        ent = tk.Entry(body, textvariable=self.name_var, font=F_BODY,
                       bg=SURFACE2, fg=WHITE, insertbackground=WHITE,
                       relief="flat", bd=0, highlightthickness=1,
                       highlightbackground=BORDER, highlightcolor=GOLD)
        ent.pack(fill="x", pady=(4,16), ipady=7)
        ent.focus()

        tk.Label(body, text="RESET SCHEDULE", font=F_HEAD, bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0,6))
        self.reset_var = tk.StringVar(value="thursday")
        for val, label in [("sunday",   reset_local_label(6)),
                            ("thursday", reset_local_label(3)),
                            ("5day",     "5 Days After Completion")]:
            tk.Radiobutton(body, text=label, variable=self.reset_var, value=val,
                           font=F_SMALL, bg=BG, fg=TEXT, selectcolor=SURFACE2,
                           activebackground=BG, activeforeground=GOLD, bd=0
                           ).pack(anchor="w", pady=1)

        btns = tk.Frame(body, bg=BG)
        btns.pack(fill="x", pady=(16,0))

        add = tk.Label(btns, text="Add Weekly", font=("Segoe UI",9,"bold"),
                       bg=GOLD, fg="#000", padx=16, pady=7, cursor="hand2")
        add.pack(side="left")
        add.bind("<Button-1>", lambda e: self._submit())

        cancel = tk.Label(btns, text="Cancel", font=F_SMALL,
                          bg=SURFACE2, fg=TEXT_MID, padx=16, pady=7, cursor="hand2")
        cancel.pack(side="left", padx=8)
        cancel.bind("<Button-1>", lambda e: self.top.destroy())

        self.top.bind("<Return>", lambda e: self._submit())

    def _submit(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing Name", "Enter a name.", parent=self.top)
            return
        self.result = (name, self.reset_var.get())
        self.top.destroy()


# ── Tooltip ──────────────────────────────────────────────────────────────────
class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text   = text
        self.tw     = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, event=None):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        tk.Frame(self.tw, bg=GOLD, padx=1, pady=1).pack()
        inner = tk.Frame(self.tw, bg=SURFACE2, padx=10, pady=5)
        inner.pack()
        tk.Label(inner, text=self.text, font=("Segoe UI", 9),
                 bg=SURFACE2, fg=TEXT).pack()

    def _hide(self, event=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("820x560")
    BDOTracker(root)
    root.mainloop()
