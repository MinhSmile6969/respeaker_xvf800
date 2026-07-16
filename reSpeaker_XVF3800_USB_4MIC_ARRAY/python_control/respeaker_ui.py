#!/usr/bin/env python3
"""reSpeaker XVF3800 Control Panel — GUI for monitoring, control, and firmware flashing"""

import sys
import os
import time
import math
import threading
import subprocess
import re
import glob
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from xvf_host import ReSpeaker, find, PARAMETERS

FIRMWARE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "xmos_firmwares"))
AUTO_REFRESH_MS = 1500

# ── Colour palette ─────────────────────────────────────────────────────────────
CH   = "#1a2e44"        # header background (dark navy)
CHF  = "#ecf0f1"        # header foreground
CBG  = "#eef2f7"        # window background
CCARD= "#ffffff"        # card / row background
CACC = "#2980b9"        # accent blue
COK  = "#27ae60"        # green success
CWRN = "#e67e22"        # orange warning
CERR = "#e74c3c"        # red error
CTX  = "#1c2833"        # primary text
CMT  = "#6b7785"        # muted text
CBRD = "#cdd4db"        # border
CR1  = "#f5f7fa"        # row odd
CR2  = "#ffffff"        # row even

LIVE_PARAMS = [
    "DOA_VALUE", "AEC_AZIMUTH_VALUES", "AEC_SPENERGY_VALUES",
    "AUDIO_MGR_SELECTED_AZIMUTHS", "AEC_AECPATHCHANGE", "AEC_AECCONVERGED", "AEC_RT60",
]

GROUPS = [
    ("Firmware",   ["VERSION", "BLD_MSG", "BLD_HOST", "BLD_REPO_HASH",
                    "BLD_MODIFIED", "BOOT_STATUS", "USB_BIT_DEPTH"]),
    ("Live",       ["DOA_VALUE", "AEC_AZIMUTH_VALUES", "AEC_SPENERGY_VALUES",
                    "AUDIO_MGR_SELECTED_AZIMUTHS", "AEC_AECPATHCHANGE",
                    "AEC_AECCONVERGED", "AEC_RT60",
                    "AEC_CURRENT_IDLE_TIME", "AEC_MIN_IDLE_TIME",
                    "PP_CURRENT_IDLE_TIME",  "PP_MIN_IDLE_TIME",
                    "AUDIO_MGR_CURRENT_IDLE_TIME", "AUDIO_MGR_MIN_IDLE_TIME",
                    "I2S_CURRENT_IDLE_TIME", "I2S_MIN_IDLE_TIME", "I2S_INACTIVE"]),
    ("Audio",      ["AUDIO_MGR_MIC_GAIN", "AUDIO_MGR_REF_GAIN", "AUDIO_MGR_SYS_DELAY",
                    "AUDIO_MGR_OP_L", "AUDIO_MGR_OP_R", "AUDIO_MGR_SELECTED_CHANNELS",
                    "AUDIO_MGR_OP_PACKED", "AUDIO_MGR_OP_UPSAMPLE",
                    "AUDIO_MGR_FAR_END_DSP_ENABLE", "I2S_DAC_DSP_ENABLE", "I2S_INPUT_PACKED"]),
    ("AEC",        ["AEC_NUM_MICS", "AEC_NUM_FARENDS", "AEC_MIC_ARRAY_TYPE", "AEC_MIC_ARRAY_GEO",
                    "SHF_BYPASS", "AEC_HPFONOFF", "AEC_AECSILENCELEVEL", "AEC_AECEMPHASISONOFF",
                    "AEC_FAR_EXTGAIN", "AEC_PCD_COUPLINGI", "AEC_PCD_MINTHR", "AEC_PCD_MAXTHR",
                    "AEC_ASROUTONOFF", "AEC_ASROUTGAIN", "AEC_FIXEDBEAMSONOFF",
                    "AEC_FIXEDBEAMSAZIMUTH_VALUES", "AEC_FIXEDBEAMSELEVATION_VALUES",
                    "AEC_FIXEDBEAMSGATING", "AEC_FIXEDBEAMNOISETHR"]),
    ("PostProc",   ["PP_AGCONOFF", "PP_AGCMAXGAIN", "PP_AGCDESIREDLEVEL", "PP_AGCGAIN",
                    "PP_AGCTIME", "PP_AGCFASTTIME", "PP_AGCALPHAFASTGAIN",
                    "PP_AGCALPHASLOW", "PP_AGCALPHAFAST",
                    "PP_LIMITONOFF", "PP_LIMITPLIMIT", "PP_MIN_NS", "PP_MIN_NN",
                    "PP_ECHOONOFF", "PP_GAMMA_E", "PP_GAMMA_ETAIL", "PP_GAMMA_ENL",
                    "PP_NLATTENONOFF", "PP_NLAEC_MODE", "PP_MGSCALE",
                    "PP_FMIN_SPEINDEX", "PP_DTSENSITIVE",
                    "PP_ATTNS_MODE", "PP_ATTNS_NOMINAL", "PP_ATTNS_SLOPE"]),
    ("LED",        ["LED_EFFECT", "LED_BRIGHTNESS", "LED_GAMMIFY", "LED_SPEED",
                    "LED_COLOR", "LED_DOA_COLOR", "LED_RING_COLOR"]),
    ("GPIO",       ["GPO_READ_VALUES", "GPO_WRITE_VALUE", "GPO_PORT_PIN_INDEX",
                    "GPO_PIN_ACTIVE_LEVEL", "GPO_PIN_VAL"]),
    ("System",     ["SAVE_CONFIGURATION", "CLEAR_CONFIGURATION", "REBOOT",
                    "MAX_CONTROL_TIME", "RESET_MAX_CONTROL_TIME",
                    "AUDIO_MGR_RESET_MIN_IDLE_TIME", "I2S_RESET_MIN_IDLE_TIME",
                    "AEC_RESET_MIN_IDLE_TIME", "PP_RESET_MIN_IDLE_TIME",
                    "AEC_FILTER_CMD_ABORT", "PP_NL_MODEL_CMD_ABORT",
                    "PP_EQUALIZATION_CMD_ABORT"]),
]

CONFIRM_CMDS = {
    "SAVE_CONFIGURATION":  "Save current configuration to flash?",
    "CLEAR_CONFIGURATION": "Clear ALL saved config and revert to factory defaults?\n(Takes effect after reboot)",
    "REBOOT":              "Reboot the device?\nAll unsaved settings will be lost.",
}


# ── Utility helpers ─────────────────────────────────────────────────────────────

def format_value(name, result):
    if result is None:
        return "—"
    param = PARAMETERS.get(name)
    if not param:
        return str(result)
    dtype = param[4]

    if name == "DOA_VALUE":
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            tag = "YES" if result[1] else "NO"
            return f"{result[0]}°    Speech: {tag}"
        return str(result)

    if name in ("LED_COLOR", "LED_DOA_COLOR", "LED_RING_COLOR"):
        if isinstance(result, (list, tuple)):
            return "  ".join(f"0x{v:06X}" for v in result)
        return f"0x{int(result):06X}"

    if dtype == "radians":
        if isinstance(result, (list, tuple)):
            return "  |  ".join(f"{math.degrees(v):.1f}°" for v in result)
        return f"{math.degrees(result):.1f}°"

    if dtype == "char":
        return result if isinstance(result, str) else "".join(str(c) for c in result)

    if isinstance(result, (list, tuple)):
        return "  ".join(f"{v:.4f}" if isinstance(v, float) else str(v) for v in result)

    return f"{result:.4f}" if isinstance(result, float) else str(result)


def parse_input(name, text):
    param = PARAMETERS[name]
    dtype, count = param[4], param[2]
    parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
    if len(parts) != count:
        raise ValueError(f"Expected {count} value(s), got {len(parts)}")
    values = []
    for p in parts:
        if p.lower().startswith("0x"):
            val = int(p, 16)
        else:
            val = float(p) if ("." in p or "e" in p.lower()) else int(p)
        values.append(float(val) if dtype in ("float", "radians") else int(val))
    return values


def fw_label(filepath):
    """Return a human-readable label for a firmware .bin file."""
    base = os.path.splitext(os.path.basename(filepath))[0]
    vm = re.search(r'v(\d+\.\d+\.\d+)', base)
    ver = vm.group(1) if vm else "?"
    if "i2s_master" in base:
        kind = "I2S Master"
    elif "i2s" in base:
        kind = "I2S"
    elif "all_ff" in base or "recover" in base:
        kind = "RECOVER"
    elif "usb" in base:
        kind = "USB"
    else:
        kind = "?"
    extras = []
    if "6chl" in base:
        extras.append("6ch")
    if "48k" in base:
        extras.append("48 kHz")
    label = f"{kind}  v{ver}"
    if extras:
        label += f"  ({', '.join(extras)})"
    return label


# ── ScrollableFrame ─────────────────────────────────────────────────────────────

class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, bg=CBG, **kwargs):
        super().__init__(parent, **kwargs)
        canvas = tk.Canvas(self, highlightthickness=0, bg=bg)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.inner = tk.Frame(canvas, bg=bg)
        self.inner.bind("<Configure>",
                        lambda e: canvas.config(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=self.inner, anchor="nw")
        canvas.config(yscrollcommand=vsb.set)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def _scroll(e):
            canvas.yview_scroll(-1 if (e.num == 4 or e.delta > 0) else 1, "units")

        canvas.bind("<Enter>", lambda e: [
            canvas.bind_all("<MouseWheel>", _scroll),
            canvas.bind_all("<Button-4>",   _scroll),
            canvas.bind_all("<Button-5>",   _scroll),
        ])
        canvas.bind("<Leave>", lambda e: [
            canvas.unbind_all("<MouseWheel>"),
            canvas.unbind_all("<Button-4>"),
            canvas.unbind_all("<Button-5>"),
        ])
def _scan_pa_sinks():
    """Return list of (sink_name, display_label) from PulseAudio via pactl."""
    try:
        import shutil as _sh
        if not _sh.which("pactl"):
            return []
        r = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=3)
        default_sink = ""
        for line in r.stdout.splitlines():
            if line.startswith("Default Sink:"):
                default_sink = line.split(":", 1)[1].strip()
                break
        r2 = subprocess.run(["pactl", "list", "sinks"],
                            capture_output=True, text=True, timeout=5)
        sinks = []
        name = desc = ""
        for line in r2.stdout.splitlines():
            ls = line.strip()
            if ls.startswith("Name:"):
                name = ls.split(":", 1)[1].strip()
            elif ls.startswith("Description:"):
                desc = ls.split(":", 1)[1].strip()
                if name:
                    label = desc + (" [Default]" if name == default_sink else "")
                    sinks.append((name, label))
                    name = desc = ""
        return sinks
    except Exception:
        return []


# ── Main Application ────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("reSpeaker XVF3800 — Control Panel")
        self.geometry("1560x980")
        self.minsize(1160, 720)
        self.configure(bg=CBG)

        self.device      = None
        self._lock       = threading.RLock()
        self._auto_id    = None
        self._auto_var   = tk.BooleanVar(value=False)
        self.widgets     = {}   # name -> {val_lbl, entry}

        # compass widget refs (set in _build_compass_panel)
        self.doa_canvas     = None
        self.doa_angle_lbl  = None
        self.doa_speech_lbl = None
        self.beam_auto_lbl  = None
        self.spenergy_lbl   = None

        # flash widget refs (set in _build_flash_tab)
        self.flash_log      = None
        self.flash_progress = None
        self.flash_btn      = None
        self.dfu_status_lbl = None
        self.fw_listbox     = None
        self._fw_files      = []
        self._selected_fw   = None
        self._flash_count   = 0   # session flash counter

        # recording state (set in _build_record_tab)
        self._rec_stream     = None
        self._rec_data       = {}
        self._rec_channels   = []
        self._rec_running    = False
        self._rec_start_time = None
        self._rec_timer_id   = None
        self._rec_device_idx = None
        self._rec_max_ch     = 0
        self._rec_device_var = tk.StringVar()
        self._rec_sr_var     = tk.StringVar(value="16000")
        self._ch_vars        = []
        self._level_cvs      = []   # Canvas widgets for level meters
        self._rec_save_dir   = tk.StringVar(value=os.path.join(
            os.path.expanduser("~"), "respeaker_recordings"))
        self._audio_devices  = []   # list of (sd_index, name, max_ch)
        self._out_devices    = []   # list of (sink_name, label) for playback
        self._play_proc      = None
        self._out_device_var = tk.StringVar()

        self._apply_styles()
        self._build_ui()
        self._enable_label_copy()
        self._try_connect()

    # ── Label copy support ───────────────────────────────────────────────────
    # tk.Label text is not selectable/copyable by default; add a right-click
    # "Copy" context menu (and Ctrl/Cmd+C) to every Label in the app.

    def _enable_label_copy(self):
        self._copy_menu = tk.Menu(self, tearoff=0)
        self._copy_menu.add_command(label="Copy", command=self._copy_focused_label)
        self._copy_target = None

        self.bind_class("Label", "<Button-3>", self._on_label_right_click)
        self.bind_class("Label", "<Button-1>", self._on_label_left_click, add="+")
        self.bind_all("<Control-c>", self._on_ctrl_c)

    def _on_label_left_click(self, event):
        self._copy_target = event.widget

    def _on_label_right_click(self, event):
        widget = event.widget
        text = str(widget.cget("text") or "")
        if not text.strip():
            return
        self._copy_target = widget
        try:
            self._copy_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._copy_menu.grab_release()

    def _on_ctrl_c(self, event):
        widget = self.focus_get() or self._copy_target
        if widget is not None and widget.winfo_class() == "Label":
            self._copy_target = widget
            self._copy_focused_label()

    def _copy_focused_label(self):
        widget = self._copy_target
        if widget is None:
            return
        text = str(widget.cget("text") or "")
        if not text.strip():
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        if hasattr(self, "status") and self.status is not None:
            prev = self.status.cget("text")
            self.status.config(text="Copied to clipboard.")
            self.after(1200, lambda: self.status.config(text=prev))

    # ── Style configuration ──────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure(".", background=CBG, foreground=CTX, font=("Helvetica", 12))
        s.configure("TFrame", background=CBG)
        s.configure("TLabel", background=CBG, foreground=CTX)

        s.configure("TNotebook", background=CBG, tabmargins=[2, 5, 0, 0])
        s.configure("TNotebook.Tab", padding=[16, 7], font=("Helvetica", 11, "bold"),
                    background="#c8d4e0", foreground=CTX)
        s.map("TNotebook.Tab",
              background=[("selected", CACC),  ("active", "#b0c2d6")],
              foreground=[("selected", "white"), ("active", CTX)])

        s.configure("TButton", padding=[8, 5], font=("Helvetica", 11),
                    background="#dce4ed", foreground=CTX, relief="flat",
                    borderwidth=0)
        s.map("TButton",
              background=[("active", "#c4d0de"), ("disabled", "#e6eaef")],
              foreground=[("disabled", CMT)])

        for name, bg, hover in [
            ("Accent.TButton",  CACC,  "#2471a3"),
            ("Success.TButton", COK,   "#1e8449"),
            ("Danger.TButton",  CERR,  "#c0392b"),
            ("Warn.TButton",    CWRN,  "#ca6f1e"),
        ]:
            s.configure(name, background=bg, foreground="white")
            s.map(name, background=[("active", hover), ("disabled", "#c0c8d0")])

        s.configure("TCheckbutton", background=CH, foreground=CHF)
        s.map("TCheckbutton",
              background=[("active", "#24405e")],
              foreground=[("active", CHF)])

        s.configure("TEntry", fieldbackground="white", insertcolor=CTX, padding=[4, 3])

        s.configure("Flash.Horizontal.TProgressbar",
                    troughcolor=CBRD, background=COK,
                    lightcolor=COK, darkcolor=COK)

    # ── Top-level layout ─────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header bar ───────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CH, pady=10, padx=14)
        hdr.pack(fill="x", side="top")

        tk.Label(hdr, text="reSpeaker XVF3800", bg=CH, fg=CHF,
                 font=("Helvetica", 16, "bold")).pack(side="left")
        tk.Label(hdr, text="Control Panel", bg=CH, fg="#7fa8cc",
                 font=("Helvetica", 13)).pack(side="left", padx=(8, 22))

        self.conn_dot = tk.Label(hdr, text="●", bg=CH, fg=CERR,
                                  font=("Helvetica", 20))
        self.conn_dot.pack(side="left")
        self.conn_lbl = tk.Label(hdr, text="Disconnected", bg=CH, fg=CERR,
                                  font=("Helvetica", 12, "bold"))
        self.conn_lbl.pack(side="left", padx=(3, 18))

        for text, cmd, sty in [
            ("Connect",      self._try_connect,    "Accent.TButton"),
            ("Disconnect",   self._disconnect,      "TButton"),
            ("Refresh All",  self._refresh_all,     "TButton"),
        ]:
            ttk.Button(hdr, text=text, command=cmd, style=sty).pack(side="left", padx=3)

        ttk.Checkbutton(hdr, text="Auto-refresh Live  (1.5 s)",
                        variable=self._auto_var, command=self._toggle_auto,
                        style="TCheckbutton").pack(side="left", padx=12)

        ttk.Button(hdr, text="Save Config",
                   command=lambda: self._confirm_write(
                       "SAVE_CONFIGURATION", [1], "Save current configuration to flash?"),
                   style="Success.TButton").pack(side="right", padx=6)

        # ── Status bar ───────────────────────────────────────────────────────
        sb = tk.Frame(self, bg="#243546", height=26)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self.status = tk.Label(sb, text="Ready.", bg="#243546", fg="#b0c4d8",
                               font=("Helvetica", 11), anchor="w", padx=10)
        self.status.pack(fill="x", side="left", expand=True)

        # ── Notebook container (overlay lives here) ───────────────────────────
        self._nb_frame = tk.Frame(self, bg=CBG)
        self._nb_frame.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        nb = ttk.Notebook(self._nb_frame)
        nb.pack(fill="both", expand=True)
        for tab_name, params in GROUPS:
            self._build_param_tab(nb, tab_name, params)
        self._build_flash_tab(nb)
        self._build_record_tab(nb)

        # ── Disconnected overlay ─────────────────────────────────────────────
        self._overlay = tk.Frame(self._nb_frame, bg="#dde5ef")
        self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        # outer centering
        mid = tk.Frame(self._overlay, bg="#dde5ef")
        mid.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(mid, text="⚡", bg="#dde5ef", fg="#7fa0c4",
                 font=("Helvetica", 64)).pack(pady=(0, 12))
        tk.Label(mid, text="Device Not Connected", bg="#dde5ef", fg=CTX,
                 font=("Helvetica", 22, "bold")).pack()
        tk.Label(mid, text="reSpeaker XVF3800 was not detected on USB.",
                 bg="#dde5ef", fg=CMT, font=("Helvetica", 14)).pack(pady=(6, 2))
        tk.Label(mid,
                 text="• Connect the device via USB-C (next to 3.5 mm jack)\n"
                      "• On Linux: set udev rules so no sudo is needed (see README)\n"
                      "• Install deps:  pip install pyusb  +  sudo apt install libusb-1.0-0",
                 bg="#dde5ef", fg=CMT, font=("Helvetica", 13),
                 justify="left").pack(pady=(4, 24))
        ttk.Button(mid, text="  Connect  ", style="Accent.TButton",
                   command=self._try_connect).pack(ipadx=20, ipady=8)

    # ── Parameter tab ────────────────────────────────────────────────────────

    def _build_param_tab(self, nb, tab_name, params):
        outer = ttk.Frame(nb)
        nb.add(outer, text=f"  {tab_name}  ")

        if tab_name == "Live":
            self._build_compass_panel(outer)

        # Tab toolbar
        bar = tk.Frame(outer, bg=CBG, pady=5, padx=8)
        bar.pack(fill="x")
        ttk.Button(bar, text=f"Refresh {tab_name}",
                   command=lambda p=params: self._refresh_group(p)).pack(side="left")
        n_readable = sum(1 for n in params if n in PARAMETERS and PARAMETERS[n][3] != "wo")
        tk.Label(bar, text=f"{n_readable} readable  /  {len([n for n in params if n in PARAMETERS])} total",
                 bg=CBG, fg=CMT, font=("Helvetica", 10)).pack(side="right", padx=10)

        # Column header
        col_bg = "#d2dce8"
        ch_row = tk.Frame(outer, bg=col_bg, pady=3)
        ch_row.pack(fill="x", padx=8)
        tk.Frame(ch_row, bg=col_bg, width=4).pack(side="left")   # accent stripe gap
        for text, w in [("Parameter Name", 28), ("", 5), ("Current Value", 30),
                        ("New Value (space-separated)", 27), ("Actions", 15), ("Description", 0)]:
            kw = dict(bg=col_bg, fg="#374f65",
                      font=("Helvetica", 11, "bold"), anchor="w", padx=5, pady=2)
            if w:
                kw["width"] = w
            tk.Label(ch_row, text=text, **kw).pack(side="left")

        # Scrollable rows
        sf = ScrollableFrame(outer, bg=CBG)
        sf.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        for idx, name in enumerate(params):
            if name in PARAMETERS:
                self._add_row(sf.inner, name, idx)

    def _add_row(self, parent, name, idx):
        param  = PARAMETERS[name]
        access = param[3]
        count  = param[2]
        desc   = param[5]

        bg = CR1 if idx % 2 == 0 else CR2
        frame = tk.Frame(parent, bg=bg, pady=3)
        frame.pack(fill="x", pady=0)

        # Accent left stripe
        stripe = {"ro": "#95a5a6", "rw": COK, "wo": CWRN}.get(access, CBRD)
        tk.Frame(frame, bg=stripe, width=4).pack(side="left", fill="y")

        # Parameter name
        tk.Label(frame, text=name, bg=bg, fg=CTX,
                 font=("Courier", 11, "bold"), width=28, anchor="w",
                 padx=6).pack(side="left")

        # Access badge
        badge = {
            "ro": ("#dce0e4", "#5d6d7e"),
            "rw": ("#d5f5e3", "#1a5e34"),
            "wo": ("#fdebd0", "#7d4a0f"),
        }
        bc, fc = badge.get(access, ("#eee", "#333"))
        tk.Label(frame, text=access.upper(), bg=bc, fg=fc,
                 font=("Helvetica", 10, "bold"), width=4,
                 padx=2, pady=1).pack(side="left", padx=3)

        # Current value label
        val_lbl = tk.Label(frame, text="—", bg=bg, fg=CMT,
                           font=("Courier", 11), width=30, anchor="w")
        val_lbl.pack(side="left", padx=(4, 0))

        # Entry (writable)
        entry = None
        if access in ("rw", "wo"):
            entry = ttk.Entry(frame, width=26, font=("Courier", 11))
            entry.insert(0, " ".join(["0"] * count))
            entry.pack(side="left", padx=5)
            entry.bind("<Return>",
                       lambda e, n=name, en=entry, l=val_lbl: self._write_async(n, en, l))
        else:
            tk.Label(frame, width=27, bg=bg).pack(side="left")

        # Buttons
        btn_f = tk.Frame(frame, bg=bg)
        btn_f.pack(side="left", padx=2)
        if access in ("ro", "rw"):
            ttk.Button(btn_f, text="Read", width=6,
                       command=lambda n=name, l=val_lbl: self._read_async(n, l)).pack(side="left", padx=1)
        if access in ("rw", "wo") and entry is not None:
            ttk.Button(btn_f, text="Write", width=6,
                       command=lambda n=name, e=entry, l=val_lbl: self._write_async(n, e, l)).pack(side="left", padx=1)

        # Description
        desc_short = desc[:70] + ("…" if len(desc) > 70 else "")
        desc_lbl = tk.Label(frame, text=desc_short, bg=bg, fg=CMT,
                            font=("Helvetica", 10), anchor="w")
        desc_lbl.pack(side="left", padx=(8, 4), fill="x", expand=True)
        self._tooltip(desc_lbl, desc)
        self._tooltip(val_lbl, desc)

        self.widgets[name] = {"val_lbl": val_lbl, "entry": entry}

    # ── Compass panel ────────────────────────────────────────────────────────

    def _build_compass_panel(self, parent):
        panel = tk.Frame(parent, bg=CCARD, bd=0)
        panel.pack(fill="x", padx=8, pady=4)

        # Compass canvas
        left = tk.Frame(panel, bg=CCARD)
        left.pack(side="left", padx=14, pady=10)
        tk.Label(left, text="Direction of Arrival", bg=CCARD, fg=CTX,
                 font=("Helvetica", 12, "bold")).pack(pady=(0, 4))
        self.doa_canvas = tk.Canvas(left, width=230, height=230, bg="#f9fbfd",
                                    highlightthickness=1, highlightbackground=CBRD)
        self.doa_canvas.pack()
        self._draw_compass_bg()
        self._draw_needle(0, False)

        # Stats
        mid = tk.Frame(panel, bg=CCARD)
        mid.pack(side="left", padx=24, pady=10, anchor="n")
        stats = [
            ("DoA Angle",          "—°", "doa_angle_lbl",  ("Helvetica", 32, "bold"), CACC),
            ("Speech Activity",    "—",  "doa_speech_lbl", ("Helvetica", 15),          CMT),
            ("Auto-beam Azimuth",  "—",  "beam_auto_lbl",  ("Helvetica", 14),          CTX),
            ("Speech Energy (Auto)","—", "spenergy_lbl",   ("Helvetica", 14),          CTX),
        ]
        for i, (lbl_text, init, attr, font, fg) in enumerate(stats):
            tk.Label(mid, text=lbl_text, bg=CCARD, fg=CMT,
                     font=("Helvetica", 11)).grid(row=i, column=0, sticky="w", pady=6)
            lbl = tk.Label(mid, text=init, bg=CCARD, fg=fg, font=font)
            lbl.grid(row=i, column=1, sticky="w", padx=18)
            setattr(self, attr, lbl)

        # Separator
        tk.Frame(panel, bg=CBRD, width=1).pack(side="left", fill="y", padx=8, pady=10)

        # Quick actions
        qk = tk.Frame(panel, bg=CCARD)
        qk.pack(side="left", padx=10, pady=10, anchor="n")
        tk.Label(qk, text="Quick Actions", bg=CCARD, fg=CTX,
                 font=("Helvetica", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Button(qk, text="Refresh DoA", width=18, style="Accent.TButton",
                   command=self._refresh_doa).pack(pady=3)
        ttk.Button(qk, text="Refresh All Live", width=18,
                   command=lambda: self._refresh_group(LIVE_PARAMS)).pack(pady=3)

        # Bottom separator
        tk.Frame(parent, bg=CBRD, height=1).pack(fill="x", padx=8)

    def _refresh_doa(self):
        w = self.widgets.get("DOA_VALUE")
        if w:
            self._read_async("DOA_VALUE", w["val_lbl"])

    def _draw_compass_bg(self):
        c = self.doa_canvas
        cx, cy, r = 115, 115, 100
        c.create_oval(cx - r, cy - r, cx + r, cy + r,
                      outline=CBRD, width=2, fill="#f9fbfd", tags="bg")
        # inner ring
        c.create_oval(cx - 10, cy - 10, cx + 10, cy + 10,
                      outline=CBRD, width=1, fill="#e8ecf0", tags="bg")
        for deg in range(0, 360, 10):
            rad = math.radians(deg - 90)
            major = deg % 30 == 0
            ir = r - (15 if major else 7)
            x1, y1 = cx + ir * math.cos(rad),  cy + ir * math.sin(rad)
            x2, y2 = cx + r  * math.cos(rad),  cy + r  * math.sin(rad)
            c.create_line(x1, y1, x2, y2,
                          fill="#aaa" if major else "#ddd",
                          width=2 if major else 1, tags="bg")
            if major:
                tx = cx + (r + 17) * math.cos(rad)
                ty = cy + (r + 17) * math.sin(rad)
                c.create_text(tx, ty, text=f"{deg}°",
                              font=("Helvetica", 9), fill=CMT, tags="bg")

    def _draw_needle(self, angle_deg, speech):
        c = self.doa_canvas
        c.delete("needle")
        cx, cy, r = 115, 115, 100
        color = CERR if speech else CACC
        rad = math.radians(angle_deg - 90)
        nr = r - 18
        nx, ny = cx + nr * math.cos(rad), cy + nr * math.sin(rad)
        # shadow
        c.create_line(cx + 1, cy + 1, nx + 1, ny + 1,
                      fill="#ccc", width=3, tags="needle")
        # needle
        c.create_line(cx, cy, nx, ny, fill=color, width=3,
                      arrow="last", arrowshape=(14, 18, 5), tags="needle")
        c.create_oval(cx - 6, cy - 6, cx + 6, cy + 6,
                      fill=color, outline="white", width=2, tags="needle")

    # ── Flash Firmware tab ───────────────────────────────────────────────────

    def _build_flash_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text="  Flash Firmware  ")

        # Warning banner
        warn = tk.Frame(outer, bg="#fef9e7", pady=7, padx=14)
        warn.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(warn, text="Note:", bg="#fef9e7", fg="#7d6608",
                 font=("Helvetica", 11, "bold")).pack(side="left")
        tk.Label(warn,
                 text="  Use the XMOS USB-C port (near the 3.5 mm jack) to flash firmware.  "
                      "Device will restart automatically after flashing.",
                 bg="#fef9e7", fg="#7d6608", font=("Helvetica", 11)).pack(side="left")

        # Two-column layout
        body = tk.Frame(outer, bg=CBG)
        body.pack(fill="both", expand=True, padx=8, pady=6)

        # ── Left: firmware selector ───────────────────────────────────────
        left = tk.Frame(body, bg=CCARD, highlightthickness=1,
                        highlightbackground=CBRD)
        left.pack(side="left", fill="y", padx=(0, 6), ipadx=8, ipady=8)

        tk.Label(left, text="Available Firmware Files", bg=CCARD, fg=CTX,
                 font=("Helvetica", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 6))
        tk.Frame(left, bg=CBRD, height=1).pack(fill="x", padx=8, pady=2)

        # Listbox
        lb_f = tk.Frame(left, bg=CCARD)
        lb_f.pack(fill="both", expand=True, padx=12, pady=8)
        vsb = ttk.Scrollbar(lb_f, orient="vertical")
        self.fw_listbox = tk.Listbox(
            lb_f, font=("Courier", 11), height=14, width=50,
            yscrollcommand=vsb.set,
            selectbackground=CACC, selectforeground="white",
            bg="white", fg=CTX, activestyle="none",
            relief="flat", bd=1,
            highlightthickness=1, highlightbackground=CBRD)
        vsb.config(command=self.fw_listbox.yview)
        self.fw_listbox.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.fw_listbox.bind("<<ListboxSelect>>", self._on_fw_select)

        # Populate from firmware directory
        self._fw_files = []
        for subdir in ["usb", "i2s", "recover"]:
            path = os.path.join(FIRMWARE_DIR, subdir)
            if os.path.exists(path):
                files = sorted(glob.glob(os.path.join(path, "*.bin")))
                if files:
                    self.fw_listbox.insert("end", f"── {subdir.upper()} ──────────────────────")
                    self.fw_listbox.itemconfig("end", fg=CMT, selectbackground=CBG,
                                               selectforeground=CMT)
                    for f in files:
                        self._fw_files.append(f)
                        self.fw_listbox.insert("end", f"  {fw_label(f)}")
                        # store index mapping
                    self.fw_listbox.insert("end", "")
                    self._fw_files.append(None)   # blank separator placeholder

        if not self._fw_files:
            self.fw_listbox.insert("end", f"  No .bin files found in:")
            self.fw_listbox.insert("end", f"  {FIRMWARE_DIR}")

        ttk.Button(left, text="Browse for .bin file...",
                   command=self._browse_fw).pack(anchor="w", padx=12, pady=(0, 4))

        tk.Frame(left, bg=CBRD, height=1).pack(fill="x", padx=8, pady=2)
        self.fw_info_lbl = tk.Label(left, text="No file selected.", bg=CCARD, fg=CMT,
                                     font=("Helvetica", 11), wraplength=340,
                                     justify="left")
        self.fw_info_lbl.pack(anchor="w", padx=12, pady=8)

        # ── Right: DFU status + flash controls + log ──────────────────────
        right = tk.Frame(body, bg=CBG)
        right.pack(side="left", fill="both", expand=True)

        # DFU status card
        dfu_card = tk.Frame(right, bg=CCARD, highlightthickness=1,
                             highlightbackground=CBRD)
        dfu_card.pack(fill="x", pady=(0, 6), ipadx=8, ipady=6)

        tk.Label(dfu_card, text="DFU Tool Status", bg=CCARD, fg=CTX,
                 font=("Helvetica", 12, "bold")).pack(anchor="w", padx=12, pady=(8, 4))

        dfu_btn_row = tk.Frame(dfu_card, bg=CCARD)
        dfu_btn_row.pack(anchor="w", padx=12, pady=4)
        ttk.Button(dfu_btn_row, text="Check dfu-util",
                   command=self._check_dfu_util).pack(side="left", padx=(0, 6))
        ttk.Button(dfu_btn_row, text="Scan DFU Devices",
                   command=self._scan_dfu).pack(side="left")

        self.dfu_status_lbl = tk.Label(dfu_card,
                                        text="Click 'Check dfu-util' to verify installation.",
                                        bg=CCARD, fg=CMT, font=("Helvetica", 11),
                                        wraplength=560, justify="left")
        self.dfu_status_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # Flash button + progress
        flash_row = tk.Frame(right, bg=CBG)
        flash_row.pack(fill="x", pady=4)

        self.flash_btn = ttk.Button(flash_row, text="Flash Selected Firmware",
                                     command=self._do_flash,
                                     style="Danger.TButton", width=26)
        self.flash_btn.pack(side="left", padx=(0, 10))

        self.flash_progress = ttk.Progressbar(
            flash_row, length=320, mode="determinate",
            style="Flash.Horizontal.TProgressbar")
        self.flash_progress.pack(side="left")

        self.flash_pct_lbl = tk.Label(flash_row, text="", bg=CBG, fg=CTX,
                                       font=("Helvetica", 11, "bold"), width=5)
        self.flash_pct_lbl.pack(side="left", padx=6)

        # Log output
        tk.Label(right, text="Flash Output Log", bg=CBG, fg=CTX,
                 font=("Helvetica", 12, "bold")).pack(anchor="w", pady=(6, 4))

        log_wrap = tk.Frame(right, bg=CBG)
        log_wrap.pack(fill="both", expand=True)

        log_vsb = ttk.Scrollbar(log_wrap, orient="vertical")
        log_hsb = ttk.Scrollbar(log_wrap, orient="horizontal")
        self.flash_log = tk.Text(
            log_wrap, height=14, font=("Courier", 11),
            bg="#1a2535", fg="#a8c6e8",
            insertbackground="white",
            yscrollcommand=log_vsb.set,
            xscrollcommand=log_hsb.set,
            wrap="none", state="disabled",
            relief="flat", bd=0,
            padx=8, pady=6)
        log_vsb.config(command=self.flash_log.yview)
        log_hsb.config(command=self.flash_log.xview)
        log_vsb.pack(side="right",  fill="y")
        log_hsb.pack(side="bottom", fill="x")
        self.flash_log.pack(fill="both", expand=True)

    # ── Flash helpers ────────────────────────────────────────────────────────

    def _on_fw_select(self, _event=None):
        sel = self.fw_listbox.curselection()
        if not sel:
            return
        # Map listbox index to _fw_files index (accounting for headers/blanks)
        # Rebuild a direct mapping by walking the listbox items
        lb_idx = sel[0]
        file_idx = -1
        fw_idx = 0
        for i in range(lb_idx + 1):
            txt = self.fw_listbox.get(i)
            if txt.startswith("──") or txt.strip() == "":
                pass
            else:
                if i == lb_idx:
                    file_idx = fw_idx
                fw_idx += 1

        if file_idx < 0 or file_idx >= len([f for f in self._fw_files if f]):
            return
        # Get actual (non-None) files in order
        real_files = [f for f in self._fw_files if f]
        if file_idx >= len(real_files):
            return
        path = real_files[file_idx]
        self._selected_fw = path
        size_kb = os.path.getsize(path) / 1024
        self.fw_info_lbl.config(
            text=f"{fw_label(path)}\n{os.path.basename(path)}\n{size_kb:.1f} KB",
            fg=CTX)

    def _browse_fw(self):
        path = filedialog.askopenfilename(
            title="Select Firmware .bin File",
            initialdir=FIRMWARE_DIR,
            filetypes=[("Binary files", "*.bin"), ("All files", "*.*")])
        if path:
            self._selected_fw = path
            size_kb = os.path.getsize(path) / 1024
            self.fw_info_lbl.config(
                text=f"Custom: {os.path.basename(path)}\n{size_kb:.1f} KB",
                fg=CTX)

    def _check_dfu_util(self):
        import shutil
        if shutil.which("dfu-util"):
            try:
                out = subprocess.check_output(
                    ["dfu-util", "-V"], stderr=subprocess.STDOUT, text=True)
                ver = out.strip().split("\n")[0]
                self.dfu_status_lbl.config(
                    text=f"dfu-util installed:  {ver}", fg=COK)
            except Exception as e:
                self.dfu_status_lbl.config(text=f"dfu-util found but error: {e}", fg=CWRN)
        else:
            self.dfu_status_lbl.config(
                text="dfu-util NOT found.  Install with:  sudo apt install dfu-util",
                fg=CERR)

    def _scan_dfu(self):
        self.dfu_status_lbl.config(text="Scanning for DFU devices…", fg=CMT)
        self.update_idletasks()
        try:
            out = subprocess.check_output(
                ["dfu-util", "-l"], stderr=subprocess.STDOUT, text=True, timeout=10)
            if "Found DFU:" in out:
                lines = [l.strip() for l in out.splitlines() if "Found DFU:" in l]
                self.dfu_status_lbl.config(
                    text=f"Found {len(lines)} DFU device(s):\n" + "\n".join(lines),
                    fg=COK)
            elif "Cannot open DFU" in out:
                self.dfu_status_lbl.config(
                    text="Device found but cannot open — udev rule missing.\n"
                         "Run: sudo udevadm control --reload-rules && sudo udevadm trigger\n"
                         "and confirm your user is in the 'plugdev' group (see README).",
                    fg=CWRN)
            else:
                self.dfu_status_lbl.config(
                    text="No DFU devices detected. Check USB connection.", fg=CWRN)
        except FileNotFoundError:
            self.dfu_status_lbl.config(
                text="dfu-util not found.  Install: sudo apt install dfu-util", fg=CERR)
        except subprocess.TimeoutExpired:
            self.dfu_status_lbl.config(text="Scan timed out.", fg=CWRN)
        except Exception as e:
            self.dfu_status_lbl.config(text=f"Error: {e}", fg=CERR)

    def _do_flash(self):
        fw_path = self._selected_fw
        if not fw_path or not os.path.exists(fw_path):
            messagebox.showerror("No File Selected", "Please select a firmware file first.")
            return

        import shutil
        if not shutil.which("dfu-util"):
            messagebox.showerror("Missing Tool",
                "dfu-util not installed.\n\nInstall with:\n  sudo apt install dfu-util")
            return

        confirm_msg = (
            f"Flash firmware to device?\n\n"
            f"File:  {os.path.basename(fw_path)}\n"
            f"Type:  {fw_label(fw_path)}\n\n"
            f"⚠  DO NOT disconnect USB during flashing.\n"
            f"   Interrupted flash can corrupt firmware.\n\n"
            f"ℹ  DFU overwrites the upgrade partition each time\n"
            f"   (no storage accumulation, factory partition is\n"
            f"   always kept safe as recovery).\n\n"
            f"Flashed {self._flash_count} time(s) this session."
        )
        if not messagebox.askyesno("Confirm Flash", confirm_msg):
            return

        # Release USB before flashing
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
            self.conn_dot.config(fg=CWRN)
            self.conn_lbl.config(text="Released for DFU", fg=CWRN)

        # Reset UI
        self._log_clear()
        self.flash_progress.config(mode="indeterminate", value=0)
        self.flash_progress.start(10)
        self.flash_btn.config(state="disabled", text="Flashing…")
        self.flash_pct_lbl.config(text="")

        cmd = ["dfu-util", "-R", "-e", "-a", "1", "-D", fw_path]
        self._log_append(f"$ {' '.join(cmd)}\n\n")

        def run():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=0)
                buf = ""
                while True:
                    ch = proc.stdout.read(1)
                    if not ch:
                        break
                    if ch == "\r":
                        if buf.strip():
                            line = buf.strip()
                            self.after(0, lambda l=line: self._process_flash_line(l))
                        buf = ""
                    elif ch == "\n":
                        buf += ch
                        line = buf.rstrip()
                        buf = ""
                        if line:
                            self.after(0, lambda l=line: self._process_flash_line(l))
                    else:
                        buf += ch
                if buf.strip():
                    self.after(0, lambda l=buf.strip(): self._process_flash_line(l))
                proc.wait()
                self.after(0, lambda rc=proc.returncode: self._flash_done(rc))
            except Exception as e:
                self.after(0, lambda err=str(e): self._flash_error(err))

        threading.Thread(target=run, daemon=True).start()

    def _process_flash_line(self, line):
        self._log_append(line + "\n")
        m = re.search(r'(\d+)%', line)
        if m:
            pct = int(m.group(1))
            if self.flash_progress["mode"] == "indeterminate":
                self.flash_progress.stop()
                self.flash_progress.config(mode="determinate")
            self.flash_progress["value"] = pct
            self.flash_pct_lbl.config(text=f"{pct}%")

    def _flash_done(self, rc):
        self.flash_progress.stop()
        self.flash_progress.config(mode="determinate")
        if rc == 0:
            self._flash_count += 1
            self.flash_progress["value"] = 100
            self.flash_pct_lbl.config(text="100%")
            self._log_append(
                f"\n[ Flash completed successfully  —  "
                f"session count: {self._flash_count} ]\n"
                f"[ DFU overwrites upgrade partition each time — no storage accumulation ]\n"
                f"[ Factory partition (alt=0) is always intact as recovery ]\n"
            )
            self.flash_btn.config(state="normal", text="Flash Selected Firmware")
            messagebox.showinfo("Flash Complete",
                "Firmware flashed successfully!\n\n"
                "The device is restarting.\n"
                "Wait a few seconds, then click Connect.\n\n"
                "Channel count (2ch / 6ch) will update\n"
                "automatically once reconnected.")
        else:
            self._log_append(f"\n[ Failed — exit code {rc} ]\n")
            self.flash_btn.config(state="normal", text="Flash Selected Firmware")
            messagebox.showerror("Flash Failed",
                f"dfu-util exited with code {rc}.\n"
                "Check the output log for details.\n\n"
                "Common fixes:\n"
                "• udev rule not set — see README 'USB Permissions Setup'\n"
                "• Device not in DFU mode — hold Mute + replug USB\n"
                "• dfu-util not installed — sudo apt install dfu-util")

    def _flash_error(self, err):
        self.flash_progress.stop()
        self.flash_progress.config(mode="determinate")
        self._log_append(f"\n[ Error: {err} ]\n")
        self.flash_btn.config(state="normal", text="Flash Selected Firmware")
        messagebox.showerror("Flash Error", f"An error occurred:\n{err}")

    def _log_append(self, text):
        self.flash_log.config(state="normal")
        self.flash_log.insert("end", text)
        self.flash_log.see("end")
        self.flash_log.config(state="disabled")

    def _log_clear(self):
        self.flash_log.config(state="normal")
        self.flash_log.delete(1.0, "end")
        self.flash_log.config(state="disabled")

    # ── Tooltip ──────────────────────────────────────────────────────────────

    def _tooltip(self, widget, text):
        tip = [None]

        def show(e):
            tip[0] = tk.Toplevel(widget)
            tip[0].wm_overrideredirect(True)
            tip[0].wm_geometry(f"+{e.x_root + 14}+{e.y_root + 14}")
            tk.Label(tip[0], text=text, bg="#fffff0", fg=CTX,
                     relief="solid", bd=1, font=("Helvetica", 11),
                     wraplength=460, justify="left", padx=6, pady=4).pack()

        def hide(e):
            if tip[0]:
                tip[0].destroy()
                tip[0] = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    # ── Device connection ────────────────────────────────────────────────────

    def _try_connect(self):
        self.status.config(text="Connecting…")
        self.update_idletasks()
        dev = find()
        if dev:
            self.device = dev
            self.conn_dot.config(fg=COK)
            self.conn_lbl.config(text="Connected", fg=COK)
            self.status.config(text="Device connected.")
            self._overlay.place_forget()
            self._refresh_all()
            # rescan audio devices — firmware may have changed (2ch ↔ 6ch)
            # delay 2.5 s to let Linux fully re-enumerate the USB audio device
            self.after(2500, self._scan_audio_devices)
        else:
            self.device = None
            self.conn_dot.config(fg=CERR)
            self.conn_lbl.config(text="No Device", fg=CERR)
            self.status.config(text="Device not found — check USB and retry.")
            self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _disconnect(self):
        self._stop_auto()
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
        self.conn_dot.config(fg=CERR)
        self.conn_lbl.config(text="Disconnected", fg=CERR)
        self.status.config(text="Disconnected.")
        self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

    # ── Read / Write ─────────────────────────────────────────────────────────

    def _do_read(self, name):
        with self._lock:
            if not self.device:
                return None, "Not connected"
            try:
                return self.device.read(name), None
            except Exception as e:
                return None, str(e)

    def _read_async(self, name, lbl):
        lbl.config(text="…", fg=CMT)

        def worker():
            result, err = self._do_read(name)

            def upd():
                if err:
                    lbl.config(text=f"[{err[:28]}]", fg=CERR)
                    self.status.config(text=f"Error reading {name}: {err}")
                else:
                    txt = format_value(name, result)
                    lbl.config(text=txt, fg="#1a6b3a")
                    self.status.config(text=f"{name} = {txt}")
                    self._update_live(name, result)

            self.after(0, upd)

        threading.Thread(target=worker, daemon=True).start()

    def _write_async(self, name, entry, val_lbl):
        try:
            values = parse_input(name, entry.get())
        except ValueError as e:
            messagebox.showerror("Input Error", f"{name}:\n{e}")
            return

        if name in CONFIRM_CMDS:
            if not messagebox.askyesno("Confirm", CONFIRM_CMDS[name]):
                return

        def worker():
            with self._lock:
                if not self.device:
                    self.after(0, lambda: messagebox.showerror("Error", "Not connected"))
                    return
                try:
                    self.device.write(name, values)
                    self.after(0, lambda: self.status.config(
                        text=f"Wrote {name} = {values}"))
                    if PARAMETERS[name][3] == "rw":
                        try:
                            result = self.device.read(name)
                            txt = format_value(name, result)
                            self.after(0, lambda t=txt: val_lbl.config(text=t, fg="#1a6b3a"))
                        except Exception:
                            pass
                except Exception as e:
                    self.after(0, lambda err=str(e): messagebox.showerror(
                        "Write Error", f"{name}:\n{err}"))

        threading.Thread(target=worker, daemon=True).start()

    def _confirm_write(self, name, values, question):
        if not messagebox.askyesno("Confirm", question):
            return

        def worker():
            with self._lock:
                if not self.device:
                    self.after(0, lambda: messagebox.showerror("Error", "Not connected"))
                    return
                try:
                    self.device.write(name, values)
                    self.after(0, lambda: messagebox.showinfo("Done", f"{name} executed."))
                    self.after(0, lambda: self.status.config(text=f"{name} done"))
                except Exception as e:
                    self.after(0, lambda err=str(e): messagebox.showerror("Error", err))

        threading.Thread(target=worker, daemon=True).start()

    # ── Live compass update ──────────────────────────────────────────────────

    def _update_live(self, name, result):
        if not result or self.doa_canvas is None:
            return

        if name == "DOA_VALUE" and len(result) >= 2:
            angle, speech = int(result[0]), bool(result[1])
            self._draw_needle(angle, speech)
            self.doa_angle_lbl.config(text=f"{angle}°",
                                      fg=CERR if speech else CACC)
            self.doa_speech_lbl.config(
                text="SPEECH DETECTED" if speech else "Silence",
                fg=CERR if speech else CMT)

        elif name == "AEC_AZIMUTH_VALUES" and len(result) >= 4:
            self.beam_auto_lbl.config(text=f"{math.degrees(result[3]):.1f}°")

        elif name == "AEC_SPENERGY_VALUES" and len(result) >= 4:
            e = result[3]
            self.spenergy_lbl.config(text=f"{e:.0f}",
                                     fg=COK if e > 0 else CMT)

    # ── Refresh ──────────────────────────────────────────────────────────────

    def _refresh_group(self, params):
        if not self.device:
            self.status.config(text="No device connected.")
            return
        readable = [n for n in params
                    if n in PARAMETERS and PARAMETERS[n][3] in ("ro", "rw")]

        def worker():
            for name in readable:
                result, err = self._do_read(name)
                w = self.widgets.get(name)
                if not w:
                    continue
                lbl = w["val_lbl"]
                if err:
                    self.after(0, lambda l=lbl, e=err: l.config(
                        text=f"[{e[:22]}]", fg=CERR))
                else:
                    txt = format_value(name, result)
                    self.after(0, lambda l=lbl, t=txt: l.config(text=t, fg="#1a6b3a"))
                    self.after(0, lambda n=name, r=result: self._update_live(n, r))
                time.sleep(0.01)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_all(self):
        for _, params in GROUPS:
            self._refresh_group(params)

    # ── Auto-refresh ─────────────────────────────────────────────────────────

    def _toggle_auto(self):
        if self._auto_var.get():
            self._schedule_auto()
        else:
            self._stop_auto()

    def _schedule_auto(self):
        if not self._auto_var.get():
            return
        self._refresh_group(LIVE_PARAMS)
        self._auto_id = self.after(AUTO_REFRESH_MS, self._schedule_auto)

    def _stop_auto(self):
        if self._auto_id:
            self.after_cancel(self._auto_id)
            self._auto_id = None
        self._auto_var.set(False)

    def on_close(self):
        self._stop_auto()
        self._rec_stop()
        self._stop_playback()
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
        self.destroy()

    # ── Record Audio tab ─────────────────────────────────────────────────────

    def _build_record_tab(self, nb):
        outer = ttk.Frame(nb)
        nb.add(outer, text="  Record Audio  ")

        # Check sounddevice
        try:
            import sounddevice as _sd  # type: ignore
            import soundfile   as _sf  # type: ignore
            import numpy       as _np  # type: ignore
            self._sd = _sd
            self._sf = _sf
            self._np = _np
        except ImportError:
            frm = tk.Frame(outer, bg=CBG)
            frm.pack(expand=True)
            tk.Label(frm, text="Missing library", bg=CBG, fg=CERR,
                     font=("Helvetica", 16, "bold")).pack(pady=20)
            tk.Label(frm,
                     text=f"Install required libraries:\n\n"
                          f"  pip install sounddevice soundfile numpy",
                     bg=CBG, fg=CTX, font=("Courier", 13), justify="left").pack(pady=6)
            return

        # ── Left panel: device + channel selector ──────────────────────────
        paned = tk.PanedWindow(outer, orient="horizontal", bg=CBG,
                               sashwidth=6, sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=8, pady=6)

        left = tk.Frame(paned, bg=CCARD, highlightthickness=1,
                        highlightbackground=CBRD)
        paned.add(left, minsize=320)

        # Device row
        dev_row = tk.Frame(left, bg=CCARD)
        dev_row.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(dev_row, text="Audio Device:", bg=CCARD, fg=CTX,
                 font=("Helvetica", 11, "bold")).pack(side="left")
        self._rec_dev_cb = ttk.Combobox(dev_row, textvariable=self._rec_device_var,
                                         state="readonly", width=28,
                                         font=("Helvetica", 11))
        self._rec_dev_cb.pack(side="left", padx=6)
        self._rec_dev_cb.bind("<<ComboboxSelected>>", self._on_rec_device_select)
        ttk.Button(dev_row, text="Scan", command=self._scan_audio_devices,
                   width=6).pack(side="left")

        self._rec_dev_info = tk.Label(left, text="Click Scan to detect devices.",
                                       bg=CCARD, fg=CMT, font=("Helvetica", 10),
                                       anchor="w")
        self._rec_dev_info.pack(fill="x", padx=10, pady=(0, 6))

        tk.Frame(left, bg=CBRD, height=1).pack(fill="x", padx=8, pady=4)

        # Sample rate
        sr_row = tk.Frame(left, bg=CCARD)
        sr_row.pack(fill="x", padx=10, pady=4)
        tk.Label(sr_row, text="Sample Rate:", bg=CCARD, fg=CTX,
                 font=("Helvetica", 11, "bold")).pack(side="left")
        sr_cb = ttk.Combobox(sr_row, textvariable=self._rec_sr_var,
                              values=["16000", "48000", "44100"],
                              state="readonly", width=10)
        sr_cb.pack(side="left", padx=6)
        self._rec_sr_cb = sr_cb   # ref for dynamic update after device probe
        tk.Label(sr_row, text="Hz", bg=CCARD, fg=CMT, font=("Helvetica", 11)).pack(side="left")
        tk.Label(sr_row,
                 text="  (USB firmware: 16000 Hz only  |  I2S firmware: 48000 Hz)",
                 bg=CCARD, fg=CMT, font=("Helvetica", 10)).pack(side="left", padx=6)

        tk.Frame(left, bg=CBRD, height=1).pack(fill="x", padx=8, pady=6)

        # Channel selector (built dynamically)
        tk.Label(left, text="Select Channels to Record:", bg=CCARD, fg=CTX,
                 font=("Helvetica", 11, "bold")).pack(anchor="w", padx=10)
        self._ch_frame = tk.Frame(left, bg=CCARD)
        self._ch_frame.pack(fill="x", padx=10, pady=6)
        tk.Label(self._ch_frame, text="Scan a device first.",
                 bg=CCARD, fg=CMT, font=("Helvetica", 11)).pack(anchor="w")

        ch_btn_row = tk.Frame(left, bg=CCARD)
        ch_btn_row.pack(fill="x", padx=10, pady=2)
        ttk.Button(ch_btn_row, text="Select All",
                   command=lambda: [v.set(True) for v in self._ch_vars]).pack(side="left", padx=(0, 4))
        ttk.Button(ch_btn_row, text="Deselect All",
                   command=lambda: [v.set(False) for v in self._ch_vars]).pack(side="left")

        tk.Frame(left, bg=CBRD, height=1).pack(fill="x", padx=8, pady=6)

        # Save directory
        save_row = tk.Frame(left, bg=CCARD)
        save_row.pack(fill="x", padx=10, pady=4)
        tk.Label(save_row, text="Save to:", bg=CCARD, fg=CTX,
                 font=("Helvetica", 11, "bold")).pack(side="left")
        ttk.Entry(save_row, textvariable=self._rec_save_dir,
                  width=22, font=("Helvetica", 10)).pack(side="left", padx=4)
        ttk.Button(save_row, text="...",
                   command=self._browse_rec_dir, width=3).pack(side="left")

        tk.Frame(left, bg=CBRD, height=1).pack(fill="x", padx=8, pady=8)

        # Record controls
        ctl = tk.Frame(left, bg=CCARD)
        ctl.pack(fill="x", padx=10, pady=4)
        self._rec_start_btn = ttk.Button(ctl, text="Start Recording",
                                          command=self._rec_start,
                                          style="Danger.TButton", width=16)
        self._rec_start_btn.pack(side="left", padx=(0, 6))
        self._rec_stop_btn  = ttk.Button(ctl, text="Stop",
                                          command=self._rec_stop,
                                          style="TButton", width=8,
                                          state="disabled")
        self._rec_stop_btn.pack(side="left")

        self._rec_status_lbl = tk.Label(left, text="Idle", bg=CCARD, fg=CMT,
                                         font=("Helvetica", 12, "bold"))
        self._rec_status_lbl.pack(anchor="w", padx=10, pady=6)

        # Level meters
        tk.Label(left, text="Input Level:", bg=CCARD, fg=CTX,
                 font=("Helvetica", 11, "bold")).pack(anchor="w", padx=10)
        self._levels_frame = tk.Frame(left, bg=CCARD)
        self._levels_frame.pack(fill="x", padx=10, pady=4)
        tk.Label(self._levels_frame, text="(no device selected)",
                 bg=CCARD, fg=CMT, font=("Helvetica", 10)).pack(anchor="w")

        # ── Right panel: recordings browser ───────────────────────────────
        right = tk.Frame(paned, bg=CBG)
        paned.add(right, minsize=300)

        hdr_r = tk.Frame(right, bg=CBG)
        hdr_r.pack(fill="x", pady=(4, 6))
        tk.Label(hdr_r, text="Recordings", bg=CBG, fg=CTX,
                 font=("Helvetica", 13, "bold")).pack(side="left")
        ttk.Button(hdr_r, text="Refresh",
                   command=self._refresh_recordings).pack(side="left", padx=8)
        ttk.Button(hdr_r, text="Open Folder",
                   command=self._open_rec_folder).pack(side="left")

        # Treeview
        tree_frame = tk.Frame(right, bg=CBG)
        tree_frame.pack(fill="both", expand=True)
        tv_vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        self._rec_tree = ttk.Treeview(tree_frame, columns=("size", "path"),
                                       show="tree headings",
                                       yscrollcommand=tv_vsb.set,
                                       selectmode="browse")
        tv_vsb.config(command=self._rec_tree.yview)
        self._rec_tree.heading("#0",    text="File / Date",    anchor="w")
        self._rec_tree.heading("size",  text="Size",           anchor="e")
        self._rec_tree.heading("path",  text="Path",           anchor="w")
        self._rec_tree.column("#0",    width=260, stretch=True)
        self._rec_tree.column("size",  width=70,  stretch=False, anchor="e")
        self._rec_tree.column("path",  width=0,   stretch=False)   # hidden
        self._rec_tree.pack(side="left", fill="both", expand=True)
        tv_vsb.pack(side="right", fill="y")
        self._rec_tree.bind("<Double-1>", self._on_tree_dbl)
        self._rec_tree.bind("<Button-3>", self._on_tree_rclick)

        # Output device selector
        out_row = tk.Frame(right, bg=CBG, pady=4)
        out_row.pack(fill="x")
        tk.Label(out_row, text="Output device:", bg=CBG, fg=CTX,
                 font=("Helvetica", 11, "bold")).pack(side="left", padx=(0, 6))
        self._out_dev_cb = ttk.Combobox(out_row, textvariable=self._out_device_var,
                                         state="readonly", width=36,
                                         font=("Helvetica", 11))
        self._out_dev_cb.pack(side="left")
        self._out_dev_lbl = tk.Label(out_row, text="scanning...", bg=CBG, fg=CMT,
                                      font=("Helvetica", 10))
        self._out_dev_lbl.pack(side="left", padx=8)

        # Playback controls
        play_row = tk.Frame(right, bg=CBG, pady=6)
        play_row.pack(fill="x")
        self._play_btn = ttk.Button(play_row, text="Play Selected",
                                     command=self._play_selected,
                                     style="Accent.TButton", width=14)
        self._play_btn.pack(side="left", padx=(0, 6))
        ttk.Button(play_row, text="Stop Playback",
                   command=self._stop_playback, width=14).pack(side="left")
        self._play_lbl = tk.Label(play_row, text="", bg=CBG, fg=CMT,
                                   font=("Helvetica", 11))
        self._play_lbl.pack(side="left", padx=10)

        # Initial populate — delay so UI renders before ALSA probing starts
        self.after(300, self._scan_audio_devices)
        self._refresh_recordings()

    # ── Recording helpers ─────────────────────────────────────────────────────

    def _scan_audio_devices(self):
        """Public entry-point kept for the Scan button and startup call."""
        self._rescan_audio_devices()

    def _scan_output_devices(self):
        """No-op: output devices are refreshed inside _rescan_audio_devices."""
        pass

    def _rescan_audio_devices(self):
        """Single-threaded rescan of ALL audio devices (input + output).

        Reinitializes PortAudio first so firmware channel-count changes
        (2ch ↔ 6ch) are reflected immediately instead of using the cached list.
        """
        if not hasattr(self, '_sd') or self._sd is None:
            return
        self._rec_dev_info.config(text="Scanning devices...", fg=CMT)
        self.update_idletasks()

        def _worker():
            # Force PortAudio to rediscover devices — without this, query_devices()
            # returns the stale list even after the firmware changes channel count.
            try:
                self._sd._terminate()
                self._sd._initialize()
            except Exception:
                pass

            try:
                devices = self._sd.query_devices()
            except Exception as e:
                self.after(0, lambda err=str(e):
                           self._rec_dev_info.config(text=f"Scan error: {err}", fg=CERR))
                return

            # ── Input devices ────────────────────────────────────────────────
            in_found = []
            in_prefer = None
            for i, d in enumerate(devices):
                if d["max_input_channels"] > 0:
                    default_sr = int(d.get("default_samplerate", 16000))
                    in_found.append((i, d["name"], d["max_input_channels"], default_sr))
                    if "respeaker" in d["name"].lower() or "xvf" in d["name"].lower():
                        in_prefer = len(in_found) - 1

            # ── Output devices via PulseAudio (pactl) ────────────────────────
            out_found  = _scan_pa_sinks()
            out_prefer = next((i for i, (_, lbl) in enumerate(out_found)
                               if "[Default]" in lbl), None)

            def _update():
                # update input combobox
                self._audio_devices = in_found
                names = [f[1] for f in in_found]
                self._rec_dev_cb["values"] = names
                if names:
                    sel = in_prefer if in_prefer is not None else 0
                    self._rec_dev_cb.current(sel)
                    self._on_rec_device_select()
                else:
                    self._rec_dev_info.config(text="No input devices found.", fg=CWRN)

                # update output combobox
                self._out_devices = out_found
                labels = [f[1] for f in out_found]
                self._out_dev_cb["values"] = labels
                if labels:
                    sel = out_prefer if out_prefer is not None else 0
                    self._out_dev_cb.current(sel)
                    self._out_dev_lbl.config(text="", fg=CMT)
                else:
                    self._out_dev_lbl.config(text="No output devices found.", fg=CWRN)

            self.after(0, _update)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_rec_device_select(self, _event=None):
        name = self._rec_device_var.get()
        for idx, dev_name, max_ch, default_sr in self._audio_devices:
            if dev_name == name:
                self._rec_device_idx = idx
                self._rec_max_ch     = max_ch
                self._rec_dev_info.config(
                    text=f"Device #{idx}  —  {max_ch} ch  —  probing sample rates...",
                    fg=CMT)
                self._rebuild_channel_widgets(max_ch)
                self._rebuild_level_widgets(max_ch)
                self._probe_sample_rates(idx, max_ch, default_sr)
                return

    def _probe_sample_rates(self, device_idx, max_ch, default_sr):
        """Find valid sample rates for the device (runs in background thread)."""
        def _worker():
            candidates = [16000, 48000, 44100, 22050, 8000]
            supported  = []
            for sr in candidates:
                try:
                    self._sd.check_input_settings(
                        device=device_idx, channels=max_ch,
                        dtype="float32", samplerate=float(sr))
                    supported.append(sr)
                except Exception:
                    pass

            def _update():
                if not supported:
                    supported.append(default_sr)
                sr_strs = [str(s) for s in supported]
                # update the sample-rate combobox to only valid values
                if hasattr(self, '_rec_sr_cb'):
                    self._rec_sr_cb["values"] = sr_strs
                # pick default_sr if valid, else first supported
                best = str(default_sr) if str(default_sr) in sr_strs else sr_strs[0]
                self._rec_sr_var.set(best)
                self._rec_dev_info.config(
                    text=f"Device #{device_idx}  —  {max_ch} ch  "
                         f"—  supported rates: {', '.join(sr_strs)} Hz",
                    fg=CTX)

            self.after(0, _update)

        threading.Thread(target=_worker, daemon=True).start()

    def _rebuild_channel_widgets(self, n_ch):
        for w in self._ch_frame.winfo_children():
            w.destroy()
        self._ch_vars = []
        per_row = 4
        for i in range(n_ch):
            var = tk.BooleanVar(value=True)
            self._ch_vars.append(var)
            row, col = divmod(i, per_row)
            ttk.Checkbutton(self._ch_frame,
                            text=f"Ch {i}",
                            variable=var).grid(row=row, column=col,
                                               sticky="w", padx=4, pady=2)

    def _rebuild_level_widgets(self, n_ch):
        for w in self._levels_frame.winfo_children():
            w.destroy()
        self._level_cvs = []
        for i in range(n_ch):
            row = tk.Frame(self._levels_frame, bg=CCARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"Ch {i}", bg=CCARD, fg=CMT,
                     font=("Courier", 10), width=5, anchor="e").pack(side="left")
            cv = tk.Canvas(row, height=12, bg="#1e2d3d",
                           highlightthickness=1, highlightbackground=CBRD)
            cv.pack(side="left", fill="x", expand=True, padx=4)
            self._level_cvs.append(cv)

    def _browse_rec_dir(self):
        path = filedialog.askdirectory(title="Select Save Directory",
                                        initialdir=self._rec_save_dir.get())
        if path:
            self._rec_save_dir.set(path)
            self._refresh_recordings()

    # ── Record start / stop ───────────────────────────────────────────────────

    def _rec_start(self):
        if self._rec_device_idx is None:
            messagebox.showwarning("No Device", "Scan and select an audio device first.")
            return

        selected_ch = [i for i, v in enumerate(self._ch_vars) if v.get()]
        if not selected_ch:
            messagebox.showwarning("No Channels", "Select at least one channel.")
            return

        samplerate = int(self._rec_sr_var.get())
        total_ch   = self._rec_max_ch

        self._rec_channels   = selected_ch
        self._rec_data       = {ch: [] for ch in selected_ch}
        self._rec_running    = False   # set True only after stream opens OK
        np_ref               = self._np

        self._rec_start_btn.config(state="disabled", text="Opening stream...")
        self._rec_stop_btn.config(state="disabled")
        self._rec_status_lbl.config(text="Connecting...", fg=CWRN)

        def _callback(indata, _frames, _t, _status):
            if not self._rec_running:
                return
            chunk = indata.copy()
            for ch in selected_ch:
                if ch < chunk.shape[1]:
                    self._rec_data[ch].append(chunk[:, ch])
            levels = {}
            for ch in selected_ch:
                if ch < chunk.shape[1]:
                    rms = float(np_ref.sqrt(np_ref.mean(chunk[:, ch] ** 2)))
                    levels[ch] = min(1.0, rms * 8)
            self.after(0, lambda lv=levels: self._update_levels(lv))

        def _open():
            try:
                stream = self._sd.InputStream(
                    device=self._rec_device_idx,
                    channels=total_ch,
                    samplerate=float(samplerate),
                    dtype="float32",
                    callback=_callback,
                    blocksize=1024,
                )
                stream.start()
                self._rec_stream     = stream
                self._rec_running    = True
                self._rec_start_time = time.time()

                def _ready():
                    self._rec_start_btn.config(state="disabled", text="Recording...")
                    self._rec_stop_btn.config(state="normal")
                    self._update_rec_timer()

                self.after(0, _ready)

            except Exception as e:
                self._rec_running = False

                def _err(msg=str(e)):
                    messagebox.showerror("Record Error",
                        f"Cannot open stream at {samplerate} Hz:\n{msg}\n\n"
                        "Try a different sample rate or re-scan devices.")
                    self._rec_start_btn.config(state="normal", text="Start Recording")
                    self._rec_stop_btn.config(state="disabled")
                    self._rec_status_lbl.config(text="Error — see dialog", fg=CERR)

                self.after(0, _err)

        threading.Thread(target=_open, daemon=True).start()

    def _rec_stop(self):
        if not self._rec_running:
            return
        self._rec_running = False
        if self._rec_timer_id:
            self.after_cancel(self._rec_timer_id)
            self._rec_timer_id = None
        if self._rec_stream:
            try:
                self._rec_stream.stop()
                self._rec_stream.close()
            except Exception:
                pass
            self._rec_stream = None

        self._rec_start_btn.config(state="normal", text="Start Recording")
        self._rec_stop_btn.config(state="disabled")
        self._rec_status_lbl.config(text="Saving...", fg=CWRN)
        self.update_idletasks()

        self._save_recordings()

    def _update_rec_timer(self):
        if not self._rec_running:
            return
        elapsed = int(time.time() - self._rec_start_time)
        m, s = divmod(elapsed, 60)
        self._rec_status_lbl.config(
            text=f"Recording  {m:02d}:{s:02d}", fg=CERR)
        self._rec_timer_id = self.after(500, self._update_rec_timer)

    def _update_levels(self, levels):
        for i, cv in enumerate(self._level_cvs):
            level = levels.get(i, 0.0)
            w = cv.winfo_width()
            h = cv.winfo_height()
            if w < 2:
                continue
            bar = max(1, int(w * level))
            color = CERR if level > 0.85 else CWRN if level > 0.5 else COK
            cv.delete("all")
            cv.create_rectangle(0, 0, bar, h, fill=color, outline="")
            cv.create_rectangle(bar, 0, w, h, fill="#1e2d3d", outline="")

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save_recordings(self):
        from datetime import datetime
        np = self._np
        sf = self._sf

        if not any(self._rec_data.values()):
            self._rec_status_lbl.config(text="No data captured.", fg=CWRN)
            return

        now      = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S")
        sr       = int(self._rec_sr_var.get())

        day_dir  = os.path.join(self._rec_save_dir.get(), date_str)
        os.makedirs(day_dir, exist_ok=True)

        saved = []
        for ch_idx in self._rec_channels:
            chunks = self._rec_data.get(ch_idx, [])
            if not chunks:
                continue
            data     = np.concatenate(chunks).astype("float32")
            filename = f"ch{ch_idx}_{date_str}_{time_str}.wav"
            filepath = os.path.join(day_dir, filename)
            sf.write(filepath, data, sr)
            saved.append(filepath)

        self._rec_data = {}
        self._rec_status_lbl.config(text=f"Saved {len(saved)} file(s).", fg=COK)
        self._refresh_recordings()

        if saved:
            self.status.config(text=f"Recorded {len(saved)} channel(s) → {day_dir}")

    # ── Recordings browser ────────────────────────────────────────────────────

    def _refresh_recordings(self):
        self._rec_tree.delete(*self._rec_tree.get_children())
        root_dir = self._rec_save_dir.get()
        if not os.path.isdir(root_dir):
            return
        for day in sorted(os.listdir(root_dir), reverse=True):
            day_path = os.path.join(root_dir, day)
            if not (os.path.isdir(day_path) and re.match(r"\d{4}-\d{2}-\d{2}", day)):
                continue
            files = sorted(
                [f for f in os.listdir(day_path) if f.endswith(".wav")],
                reverse=True)
            if not files:
                continue
            node = self._rec_tree.insert("", "end", text=f"  {day}",
                                          values=("", day_path),
                                          open=True, tags=("day",))
            for fname in files:
                fpath    = os.path.join(day_path, fname)
                size_kb  = os.path.getsize(fpath) / 1024
                size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
                self._rec_tree.insert(node, "end", text=f"    {fname}",
                                       values=(size_str, fpath), tags=("wav",))
        self._rec_tree.tag_configure("day", foreground=CACC)
        self._rec_tree.tag_configure("wav", foreground=CTX)

    def _on_tree_dbl(self, _event=None):
        self._play_selected()

    def _on_tree_rclick(self, event):
        item = self._rec_tree.identify_row(event.y)
        if not item:
            return
        self._rec_tree.selection_set(item)
        tags = self._rec_tree.item(item, "tags")
        if "wav" not in tags:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Play",   command=self._play_selected)
        menu.add_command(label="Delete", command=lambda: self._delete_selected(item))
        menu.tk_popup(event.x_root, event.y_root)

    def _get_selected_wav(self):
        sel = self._rec_tree.selection()
        if not sel:
            return None
        item = sel[0]
        if "wav" not in self._rec_tree.item(item, "tags"):
            return None
        return self._rec_tree.item(item, "values")[1]  # path column

    def _play_selected(self):
        path = self._get_selected_wav()
        if not path or not os.path.exists(path):
            messagebox.showinfo("Play", "Select a .wav file first.")
            return
        self._stop_playback()
        self._play_stop_flag = [False]

        # resolve PulseAudio sink name from selected label
        out_label = self._out_device_var.get()
        sink_name = None
        for sname, lbl in self._out_devices:
            if lbl == out_label:
                sink_name = sname
                break

        if not sink_name:
            messagebox.showwarning(
                "No Output Device",
                "No output device selected.\n\nClick 'Scan' first, then choose an output device.")
            return

        fname = os.path.basename(path)
        self.after(0, lambda: (
            self._play_lbl.config(text=fname, fg=COK),
            self.status.config(text=f"Playing: {fname}")))

        def worker():
            try:
                import shutil as _sh
                if not _sh.which("paplay"):
                    raise RuntimeError(
                        "paplay not found.\n"
                        "Install with:  sudo apt install pulseaudio-utils")
                env = os.environ.copy()
                env["PULSE_SINK"] = sink_name
                cmd = ["paplay", "--device=" + sink_name, path]
                proc = subprocess.Popen(cmd, env=env,
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
                self._play_proc = proc
                stop_flag = self._play_stop_flag
                while proc.poll() is None:
                    if stop_flag[0]:
                        proc.terminate()
                        proc.wait()
                        break
                    time.sleep(0.1)
                self._play_proc = None
                rc     = proc.returncode
                stderr = (proc.stderr.read() or b"").decode(errors="replace").strip()
                if stop_flag[0]:
                    self.after(0, lambda: self._play_lbl.config(text="", fg=CMT))
                elif rc == 0:
                    self.after(0, lambda: self._play_lbl.config(text="Done", fg=CMT))
                else:
                    msg = stderr or f"paplay exited with code {rc}"
                    self.after(0, lambda m=msg: (
                        self._play_lbl.config(text=f"Error: {m[:60]}", fg=CERR),
                        self.status.config(text=f"Playback error: {m}"),
                        messagebox.showerror("Playback Error", m)))
            except Exception as e:
                self._play_proc = None
                err_msg = str(e)
                self.after(0, lambda m=err_msg: (
                    self._play_lbl.config(text=f"Error: {m[:60]}", fg=CERR),
                    self.status.config(text=f"Playback error: {m}"),
                    messagebox.showerror("Playback Error", m)))

        threading.Thread(target=worker, daemon=True).start()

    def _stop_playback(self):
        if hasattr(self, "_play_stop_flag"):
            self._play_stop_flag[0] = True
        if self._play_proc:
            try:
                self._play_proc.terminate()
                self._play_proc.wait(timeout=2)
            except Exception:
                pass
            self._play_proc = None
        if hasattr(self, "_play_lbl"):
            self._play_lbl.config(text="", fg=CMT)

    def _delete_selected(self, item):
        path = self._rec_tree.item(item, "values")[1]
        if messagebox.askyesno("Delete", f"Delete file?\n{os.path.basename(path)}"):
            try:
                os.remove(path)
                self._refresh_recordings()
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _open_rec_folder(self):
        path = self._rec_save_dir.get()
        os.makedirs(path, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", path])
        except Exception:
            pass


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
