#!/usr/bin/env python3
"""reSpeaker XVF3800 — Web Control Panel (single file)

Dependencies:
    pip install flask pyusb
    sudo apt install libusb-1.0-0

Usage:
    python respeaker_web.py [--port 5000] [--host 0.0.0.0]
    Then open  http://<machine-ip>:5000  in any browser.
"""

import sys, os, time, math, threading, subprocess, re, glob, json, queue, argparse, socket
from datetime import datetime
from flask import Flask, jsonify, request, Response, stream_with_context

try:
    import sounddevice as _sd
    import soundfile as _sf
    import numpy as _np
    _AUDIO_OK = True
except ImportError:
    _AUDIO_OK = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
try:
    from xvf_host import ReSpeaker, find, PARAMETERS
except ImportError as _e:
    print(f"ERROR: cannot import xvf_host — {_e}")
    print("Place respeaker_web.py inside  python_control/  of the SDK folder.")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────────

FIRMWARE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "xmos_firmwares"))
AUTO_REFRESH_S = 1.5

LIVE_PARAMS = [
    "DOA_VALUE", "AEC_AZIMUTH_VALUES", "AEC_SPENERGY_VALUES",
    "AUDIO_MGR_SELECTED_AZIMUTHS", "AEC_AECPATHCHANGE", "AEC_AECCONVERGED", "AEC_RT60",
]

GROUPS = [
    ("Firmware",  ["VERSION", "BLD_MSG", "BLD_HOST", "BLD_REPO_HASH",
                   "BLD_MODIFIED", "BOOT_STATUS", "USB_BIT_DEPTH"]),
    ("Live",      ["DOA_VALUE", "AEC_AZIMUTH_VALUES", "AEC_SPENERGY_VALUES",
                   "AUDIO_MGR_SELECTED_AZIMUTHS", "AEC_AECPATHCHANGE",
                   "AEC_AECCONVERGED", "AEC_RT60",
                   "AEC_CURRENT_IDLE_TIME", "AEC_MIN_IDLE_TIME",
                   "PP_CURRENT_IDLE_TIME",  "PP_MIN_IDLE_TIME",
                   "AUDIO_MGR_CURRENT_IDLE_TIME", "AUDIO_MGR_MIN_IDLE_TIME",
                   "I2S_CURRENT_IDLE_TIME", "I2S_MIN_IDLE_TIME", "I2S_INACTIVE"]),
    ("Audio",     ["AUDIO_MGR_MIC_GAIN", "AUDIO_MGR_REF_GAIN", "AUDIO_MGR_SYS_DELAY",
                   "AUDIO_MGR_OP_L", "AUDIO_MGR_OP_R", "AUDIO_MGR_SELECTED_CHANNELS",
                   "AUDIO_MGR_OP_PACKED", "AUDIO_MGR_OP_UPSAMPLE",
                   "AUDIO_MGR_FAR_END_DSP_ENABLE", "I2S_DAC_DSP_ENABLE", "I2S_INPUT_PACKED"]),
    ("AEC",       ["AEC_NUM_MICS", "AEC_NUM_FARENDS", "AEC_MIC_ARRAY_TYPE", "AEC_MIC_ARRAY_GEO",
                   "SHF_BYPASS", "AEC_HPFONOFF", "AEC_AECSILENCELEVEL", "AEC_AECEMPHASISONOFF",
                   "AEC_FAR_EXTGAIN", "AEC_PCD_COUPLINGI", "AEC_PCD_MINTHR", "AEC_PCD_MAXTHR",
                   "AEC_ASROUTONOFF", "AEC_ASROUTGAIN", "AEC_FIXEDBEAMSONOFF",
                   "AEC_FIXEDBEAMSAZIMUTH_VALUES", "AEC_FIXEDBEAMSELEVATION_VALUES",
                   "AEC_FIXEDBEAMSGATING", "AEC_FIXEDBEAMNOISETHR"]),
    ("PostProc",  ["PP_AGCONOFF", "PP_AGCMAXGAIN", "PP_AGCDESIREDLEVEL", "PP_AGCGAIN",
                   "PP_AGCTIME", "PP_AGCFASTTIME", "PP_AGCALPHAFASTGAIN",
                   "PP_AGCALPHASLOW", "PP_AGCALPHAFAST",
                   "PP_LIMITONOFF", "PP_LIMITPLIMIT", "PP_MIN_NS", "PP_MIN_NN",
                   "PP_ECHOONOFF", "PP_GAMMA_E", "PP_GAMMA_ETAIL", "PP_GAMMA_ENL",
                   "PP_NLATTENONOFF", "PP_NLAEC_MODE", "PP_MGSCALE",
                   "PP_FMIN_SPEINDEX", "PP_DTSENSITIVE",
                   "PP_ATTNS_MODE", "PP_ATTNS_NOMINAL", "PP_ATTNS_SLOPE"]),
    ("LED",       ["LED_EFFECT", "LED_BRIGHTNESS", "LED_GAMMIFY", "LED_SPEED",
                   "LED_COLOR", "LED_DOA_COLOR", "LED_RING_COLOR"]),
    ("GPIO",      ["GPO_READ_VALUES", "GPO_WRITE_VALUE", "GPO_PORT_PIN_INDEX",
                   "GPO_PIN_ACTIVE_LEVEL", "GPO_PIN_VAL"]),
    ("System",    ["SAVE_CONFIGURATION", "CLEAR_CONFIGURATION", "REBOOT",
                   "MAX_CONTROL_TIME", "RESET_MAX_CONTROL_TIME",
                   "AUDIO_MGR_RESET_MIN_IDLE_TIME", "I2S_RESET_MIN_IDLE_TIME",
                   "AEC_RESET_MIN_IDLE_TIME", "PP_RESET_MIN_IDLE_TIME",
                   "AEC_FILTER_CMD_ABORT", "PP_NL_MODEL_CMD_ABORT",
                   "PP_EQUALIZATION_CMD_ABORT"]),
    ("Flash",     []),
]

CONFIRM_CMDS = {
    "SAVE_CONFIGURATION":  "Save current configuration to flash?",
    "CLEAR_CONFIGURATION": "Clear ALL saved config and revert to factory defaults?\n(Takes effect after reboot)",
    "REBOOT":              "Reboot the device?\nAll unsaved settings will be lost.",
}

# ── App state ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=None)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = False

_dev = None
_lock = threading.RLock()
_sse_queues: list = []
_sse_lock = threading.Lock()
_live_stop = threading.Event()
_live_stop.set()

# ── Recording state ──────────────────────────────────────────────────────────
_rec_active = False
_rec_lock = threading.Lock()
_rec_buffer: list = []
_rec_stream = None
_rec_stop_event = threading.Event()
_rec_info = {
    "device_idx": None, "device_name": "", "channels": 0,
    "samplerate": 0, "segment_sec": 60,
    "outdir": os.path.expanduser("~/respeaker_recordings"),
    "start_time": None, "segments_saved": 0,
    "last_folder": "",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def format_value(name, result):
    if result is None:
        return "—"
    param = PARAMETERS.get(name)
    if not param:
        return str(result)
    dtype = param[4]
    if name == "DOA_VALUE":
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            return f"{result[0]}°  Speech: {'YES' if result[1] else 'NO'}"
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
    base = os.path.splitext(os.path.basename(filepath))[0]
    vm = re.search(r'v(\d+\.\d+\.\d+)', base)
    ver = vm.group(1) if vm else "?"
    if "i2s_master" in base:  kind = "I2S Master"
    elif "i2s" in base:       kind = "I2S"
    elif "all_ff" in base or "recover" in base: kind = "RECOVER"
    elif "usb" in base:       kind = "USB"
    else:                     kind = "?"
    extras = []
    if "6chl" in base: extras.append("6ch")
    if "48k" in base:  extras.append("48 kHz")
    label = f"{kind}  v{ver}"
    if extras:
        label += f"  ({', '.join(extras)})"
    return label

# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return "data: " + json.dumps(data) + "\n\n"


def _broadcast(data: dict):
    msg = _sse(data)
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)

# ── Live-refresh thread ───────────────────────────────────────────────────────

def _live_loop():
    while True:
        _live_stop.wait()
        if not _live_stop.is_set():
            break
        time.sleep(AUTO_REFRESH_S)
        if _live_stop.is_set():
            break
        with _lock:
            dev = _dev
        if not dev:
            continue
        data = {}
        for name in LIVE_PARAMS:
            if name not in PARAMETERS or PARAMETERS[name][3] not in ("ro", "rw"):
                continue
            try:
                result = dev.read(name)
                raw = list(result) if isinstance(result, (list, tuple)) else [result]
                data[name] = {"raw": raw, "fmt": format_value(name, result)}
            except Exception:
                pass
        if data:
            _broadcast({"type": "live", "params": data})


def _start_live():
    _live_stop.clear()


def _stop_live():
    _live_stop.set()


threading.Thread(target=_live_loop, daemon=True).start()

# ── Recording helpers ─────────────────────────────────────────────────────────

def _find_respeaker_audio():
    """Return (idx, name, channels, sr) for first ReSpeaker input device, else None."""
    if not _AUDIO_OK:
        return None
    try:
        for i, d in enumerate(_sd.query_devices()):
            if d["max_input_channels"] <= 0:
                continue
            n = d["name"].lower()
            if "respeaker" in n or "xvf" in n or "seeed" in n:
                return (i, d["name"], d["max_input_channels"],
                        int(d.get("default_samplerate", 16000)))
    except Exception:
        pass
    return None


def _save_rec_segment(chunks, channels, sr, outdir):
    """Save each channel of `chunks` (list of (frames, ch) arrays) as ch{i}.wav."""
    if not chunks:
        return None
    data = _np.concatenate(chunks, axis=0)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = os.path.join(outdir, ts)
    os.makedirs(folder, exist_ok=True)
    for ch in range(channels):
        path = os.path.join(folder, f"ch{ch}.wav")
        _sf.write(path, data[:, ch].astype("float32"), sr, subtype="PCM_16")
    return folder


def _rec_rotate_loop():
    """Every segment_sec, swap buffer and save in a background thread."""
    global _rec_buffer
    while not _rec_stop_event.is_set():
        if _rec_stop_event.wait(_rec_info["segment_sec"]):
            break
        if not _rec_active:
            break
        with _rec_lock:
            chunks, _rec_buffer = _rec_buffer, []
        if chunks:
            folder = _save_rec_segment(
                chunks, _rec_info["channels"],
                _rec_info["samplerate"], _rec_info["outdir"])
            _rec_info["segments_saved"] += 1
            _rec_info["last_folder"] = folder or ""
            _broadcast({"type": "rec_segment", "folder": folder,
                        "count": _rec_info["segments_saved"]})


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/connect", methods=["POST"])
def api_connect():
    global _dev
    with _lock:
        if _dev:
            return jsonify(ok=True, msg="Already connected")
        try:
            usb_dev = find()
            if usb_dev is None:
                return jsonify(ok=False, msg="Device not found — check USB connection and udev rules")
            _dev = usb_dev  # find() already returns a ReSpeaker object
        except Exception as e:
            return jsonify(ok=False, msg=str(e))
    _start_live()
    _broadcast({"type": "status", "connected": True})
    return jsonify(ok=True, msg="Connected")


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    global _dev
    _stop_live()
    with _lock:
        if _dev:
            try:
                _dev.close()
            except Exception:
                pass
            _dev = None
    _broadcast({"type": "status", "connected": False})
    return jsonify(ok=True)


@app.route("/api/status")
def api_status():
    return jsonify(connected=_dev is not None)


@app.route("/api/params")
def api_params():
    out = {}
    for name, p in PARAMETERS.items():
        out[name] = {"count": p[2], "access": p[3], "dtype": p[4], "desc": p[5]}
    return jsonify(out)


@app.route("/api/read/<name>")
def api_read(name):
    if name not in PARAMETERS:
        return jsonify(ok=False, msg="Unknown parameter")
    with _lock:
        if not _dev:
            return jsonify(ok=False, msg="Not connected")
        try:
            result = _dev.read(name)
            raw = list(result) if isinstance(result, (list, tuple)) else [result]
            return jsonify(ok=True, value=raw, formatted=format_value(name, result))
        except Exception as e:
            return jsonify(ok=False, msg=str(e))


@app.route("/api/write/<name>", methods=["POST"])
def api_write(name):
    if name not in PARAMETERS:
        return jsonify(ok=False, msg="Unknown parameter")
    body = request.get_json(force=True, silent=True) or {}
    try:
        values = parse_input(name, str(body.get("value", "")))
    except (ValueError, KeyError) as e:
        return jsonify(ok=False, msg=str(e))
    with _lock:
        if not _dev:
            return jsonify(ok=False, msg="Not connected")
        try:
            _dev.write(name, values)
            readback = None
            if PARAMETERS[name][3] == "rw":
                try:
                    result = _dev.read(name)
                    readback = format_value(name, result)
                except Exception:
                    pass
            return jsonify(ok=True, readback=readback)
        except Exception as e:
            return jsonify(ok=False, msg=str(e))


@app.route("/api/live")
def api_live():
    q: queue.Queue = queue.Queue(maxsize=30)
    with _sse_lock:
        _sse_queues.append(q)

    def generate():
        try:
            yield _sse({"type": "status", "connected": _dev is not None})
            while True:
                try:
                    yield q.get(timeout=25)
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/firmware/list")
def api_firmware_list():
    files = []
    for pat in ["usb/*.bin", "i2s/*.bin", "recover/*.bin"]:
        files.extend(glob.glob(os.path.join(FIRMWARE_DIR, pat)))
    files.sort()
    return jsonify([
        {"path": f, "label": fw_label(f), "name": os.path.basename(f)}
        for f in files
    ])


@app.route("/api/firmware/flash", methods=["POST"])
def api_firmware_flash():
    global _dev
    body = request.get_json(force=True, silent=True) or {}
    fw_path = body.get("path", "")
    if not fw_path or not os.path.exists(fw_path):
        return jsonify(ok=False, msg=f"File not found: {fw_path}")
    _stop_live()
    with _lock:
        if _dev:
            try:
                _dev.close()
            except Exception:
                pass
            _dev = None
    _broadcast({"type": "status", "connected": False})

    def generate():
        cmd = ["dfu-util", "-R", "-e", "-a", "1", "-D", fw_path]
        yield _sse({"type": "log", "text": "$ " + " ".join(cmd) + "\n"})
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=0)
            buf = ""
            while True:
                ch = proc.stdout.read(1)
                if not ch:
                    break
                if ch in ("\r", "\n"):
                    if buf.strip():
                        m = re.search(r"(\d+)%", buf)
                        pct = int(m.group(1)) if m else None
                        yield _sse({"type": "log", "text": buf.strip(), "pct": pct})
                    buf = ""
                else:
                    buf += ch
            if buf.strip():
                yield _sse({"type": "log", "text": buf.strip(), "pct": None})
            proc.wait()
            yield _sse({"type": "done", "ok": proc.returncode == 0, "rc": proc.returncode})
        except Exception as e:
            yield _sse({"type": "done", "ok": False, "rc": -1, "msg": str(e)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Audio recording routes ────────────────────────────────────────────────────

@app.route("/api/audio/devices")
def api_audio_devices():
    if not _AUDIO_OK:
        return jsonify(ok=False,
            msg="sounddevice not installed — run: pip install sounddevice soundfile numpy")
    devices = []
    try:
        for i, d in enumerate(_sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append({
                    "idx": i, "name": d["name"],
                    "channels": d["max_input_channels"],
                    "samplerate": int(d.get("default_samplerate", 16000)),
                })
    except Exception as e:
        return jsonify(ok=False, msg=str(e))
    found = _find_respeaker_audio()
    detected = None
    if found:
        detected = {"idx": found[0], "name": found[1],
                    "channels": found[2], "samplerate": found[3]}
    return jsonify(ok=True, devices=devices, detected=detected)


@app.route("/api/audio/start", methods=["POST"])
def api_audio_start():
    global _rec_active, _rec_stream, _rec_buffer
    if not _AUDIO_OK:
        return jsonify(ok=False, msg="sounddevice not installed")
    if _rec_active:
        return jsonify(ok=False, msg="Already recording")

    body = request.get_json(force=True, silent=True) or {}

    if body.get("device_idx") is None:
        found = _find_respeaker_audio()
        if not found:
            return jsonify(ok=False, msg="No ReSpeaker input device found")
        idx, name, channels, sr_default = found
    else:
        idx = int(body["device_idx"])
        info = _sd.query_devices(idx)
        name = info["name"]
        channels = info["max_input_channels"]
        sr_default = int(info.get("default_samplerate", 16000))

    sr = int(body.get("samplerate") or sr_default)
    segment_sec = max(5, int(body.get("segment") or 60))
    outdir = body.get("outdir") or os.path.expanduser("~/respeaker_recordings")
    outdir = os.path.expanduser(outdir)
    try:
        os.makedirs(outdir, exist_ok=True)
    except Exception as e:
        return jsonify(ok=False, msg=f"Cannot create outdir: {e}")

    _rec_info.update({
        "device_idx": idx, "device_name": name, "channels": channels,
        "samplerate": sr, "segment_sec": segment_sec, "outdir": outdir,
        "start_time": time.time(), "segments_saved": 0, "last_folder": "",
    })

    with _rec_lock:
        _rec_buffer = []

    def _cb(indata, _frames, _t, status):
        if status:
            pass  # overflows happen but don't break recording
        with _rec_lock:
            _rec_buffer.append(indata.copy())

    try:
        _rec_stream = _sd.InputStream(
            device=idx, channels=channels, samplerate=float(sr),
            dtype="float32", callback=_cb, blocksize=1024)
        _rec_stream.start()
    except Exception as e:
        return jsonify(ok=False, msg=f"Cannot open stream: {e}")

    _rec_active = True
    _rec_stop_event.clear()
    threading.Thread(target=_rec_rotate_loop, daemon=True).start()
    _broadcast({"type": "rec_start", "info": dict(_rec_info)})
    return jsonify(ok=True, info=dict(_rec_info))


@app.route("/api/audio/stop", methods=["POST"])
def api_audio_stop():
    global _rec_active, _rec_stream, _rec_buffer
    if not _rec_active:
        return jsonify(ok=True, msg="Not recording", segments=0)

    _rec_stop_event.set()
    _rec_active = False

    if _rec_stream:
        try:
            _rec_stream.stop()
            _rec_stream.close()
        except Exception:
            pass
        _rec_stream = None

    with _rec_lock:
        chunks, _rec_buffer = _rec_buffer, []
    if chunks:
        folder = _save_rec_segment(chunks, _rec_info["channels"],
                                   _rec_info["samplerate"], _rec_info["outdir"])
        _rec_info["segments_saved"] += 1
        _rec_info["last_folder"] = folder or ""

    _broadcast({"type": "rec_stop", "count": _rec_info["segments_saved"]})
    return jsonify(ok=True, segments=_rec_info["segments_saved"])


@app.route("/api/audio/status")
def api_audio_status():
    elapsed = 0.0
    if _rec_active and _rec_info["start_time"]:
        elapsed = time.time() - _rec_info["start_time"]
    return jsonify(active=_rec_active, info=dict(_rec_info), elapsed=elapsed)


@app.route("/api/recordings")
def api_recordings():
    outdir = _rec_info["outdir"]
    if not os.path.isdir(outdir):
        return jsonify(outdir=outdir, folders=[])
    folders = []
    for entry in sorted(os.listdir(outdir), reverse=True)[:50]:
        full = os.path.join(outdir, entry)
        if not os.path.isdir(full):
            continue
        try:
            wavs = [f for f in os.listdir(full) if f.endswith(".wav")]
            size = sum(os.path.getsize(os.path.join(full, f)) for f in wavs)
        except Exception:
            wavs, size = [], 0
        folders.append({"name": entry, "path": full,
                        "channels": len(wavs), "size": size})
    return jsonify(outdir=outdir, folders=folders)


# ── HTML page ─────────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>reSpeaker XVF3800 — Web Control</title>
<style>
:root{--ch:#1a2e44;--chf:#ecf0f1;--cbg:#eef2f7;--ccard:#fff;--cacc:#2980b9;
      --cok:#27ae60;--cwrn:#e67e22;--cerr:#e74c3c;--ctx:#1c2833;--cmt:#6b7785;
      --cbrd:#cdd4db;--cr1:#f5f7fa;--cr2:#fff}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;background:var(--cbg);
     color:var(--ctx);font-size:13px;display:flex;flex-direction:column;height:100vh;overflow:hidden}

/* ── Header ── */
#hdr{background:var(--ch);color:var(--chf);padding:7px 12px;display:flex;
     align-items:center;gap:8px;flex-shrink:0;flex-wrap:wrap}
#hdr h1{font-size:14px;font-weight:700;margin-right:4px;white-space:nowrap}
#cdot{font-size:18px;color:var(--cerr);line-height:1;transition:color .3s}
#cdot.ok{color:#7ec8a0}
#clbl{font-size:12px;font-weight:600;color:var(--cerr);min-width:90px;transition:color .3s}
#clbl.ok{color:#7ec8a0}
.hbtn{padding:4px 11px;border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.1);
      color:var(--chf);border-radius:4px;cursor:pointer;font-size:12px;white-space:nowrap}
.hbtn:hover{background:rgba(255,255,255,.22)}
.hbtn.accent{background:var(--cacc);border-color:var(--cacc)}
.hbtn.green{background:var(--cok);border-color:var(--cok)}
#autolbl{font-size:12px;color:var(--chf);display:flex;align-items:center;gap:5px;cursor:pointer}
#sp{flex:1}

/* ── Tabs ── */
#tabs{background:#152335;display:flex;padding:0 8px;gap:1px;overflow-x:auto;flex-shrink:0}
.tbtn{padding:7px 13px;background:transparent;border:none;color:#7a98b4;cursor:pointer;
      font-size:12px;font-weight:600;border-bottom:3px solid transparent;white-space:nowrap}
.tbtn:hover{color:var(--chf)}
.tbtn.active{color:var(--chf);border-bottom-color:var(--cacc)}

/* ── Content ── */
#content{flex:1;overflow-y:auto;padding:10px}
.pane{display:none}.pane.active{display:block}

/* ── Toolbar ── */
.tbar{display:flex;align-items:center;gap:7px;margin-bottom:9px;flex-wrap:wrap}
.xbtn{padding:4px 11px;border:1px solid var(--cbrd);background:#fff;border-radius:4px;
      cursor:pointer;font-size:12px}
.xbtn:hover{background:var(--cr1)}
.xbtn.accent{background:var(--cacc);color:#fff;border-color:var(--cacc)}
.xbtn.ok{background:var(--cok);color:#fff;border-color:var(--cok)}

/* ── Compass ── */
#cpanel{background:var(--ccard);border:1px solid var(--cbrd);border-radius:6px;
        padding:12px 16px;margin-bottom:10px;display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start}
#cpanel h3{font-size:12px;font-weight:700;margin-bottom:6px}
#dcanv{border-radius:50%;background:#f9fbfd;border:1px solid var(--cbrd)}
.cstats{display:grid;grid-template-columns:auto auto;gap:5px 14px;align-content:start}
.cstats .sl{color:var(--cmt);font-size:11px}
.cstats .sv{font-size:13px;font-weight:700;color:var(--cacc)}
#doaang{font-size:26px}

/* ── Param table ── */
.ptbl{width:100%;border-collapse:collapse}
.ptbl th{background:var(--ch);color:var(--chf);padding:5px 8px;font-size:11px;
         text-align:left;position:sticky;top:0;z-index:2}
.ptbl td{padding:5px 8px;border-bottom:1px solid var(--cbrd);vertical-align:middle}
.ptbl tr:nth-child(odd) td{background:var(--cr1)}
.ptbl tr:nth-child(even) td{background:var(--cr2)}
.ptbl tr:hover td{background:#e8f0fa}
.pn{font-family:monospace;font-size:12px;font-weight:600;white-space:nowrap}
.pv{font-family:monospace;font-size:12px;color:var(--cmt);min-width:160px;max-width:260px;
    word-break:break-all}
.pv.ok{color:#1a6b3a}.pv.er{color:var(--cerr)}
.pe{width:130px;padding:3px 6px;border:1px solid var(--cbrd);border-radius:3px;font-size:12px}
.pb{display:flex;gap:3px}
.rb{padding:2px 7px;border:1px solid var(--cacc);color:var(--cacc);background:#fff;
    border-radius:3px;cursor:pointer;font-size:11px}
.rb:hover{background:#e8f4fc}
.wb{padding:2px 7px;border:1px solid var(--cok);color:var(--cok);background:#fff;
    border-radius:3px;cursor:pointer;font-size:11px}
.wb:hover{background:#eafbf0}
.pd{color:var(--cmt);font-size:11px;max-width:320px;overflow:hidden;
    text-overflow:ellipsis;white-space:nowrap;cursor:help}
.bro{background:#e3eaf2;color:#4a7a9b;padding:1px 5px;border-radius:3px;font-size:10px}
.brw{background:#d5f0e0;color:#1e7e4c;padding:1px 5px;border-radius:3px;font-size:10px}
.bwo{background:#fde8d8;color:#c0622e;padding:1px 5px;border-radius:3px;font-size:10px}

/* ── Flash tab ── */
.fcard{background:var(--ccard);border:1px solid var(--cbrd);border-radius:6px;
       padding:14px;margin-bottom:12px;max-width:860px}
.fcard h3{font-size:13px;font-weight:700;margin-bottom:10px}
.fwlist{list-style:none}
.fwitem{padding:7px 10px;border:1px solid var(--cbrd);border-radius:4px;margin-bottom:5px;
        cursor:pointer;font-size:12px;display:flex;align-items:center;gap:9px}
.fwitem:hover{background:var(--cr1)}
.fwitem.sel{background:#dbeeff;border-color:var(--cacc)}
.fwkind{font-size:10px;padding:2px 6px;border-radius:3px;font-weight:700;
        background:#d5e8f8;color:var(--cacc)}
.fwkind.rec{background:#fde8d8;color:var(--cerr)}
.fwn{font-family:monospace;font-size:11px;color:var(--cmt)}
#flog{font-family:monospace;font-size:11px;background:#0f1923;color:#a8c8e0;
      padding:10px;border-radius:4px;height:180px;overflow-y:auto;white-space:pre-wrap}
#fprog{width:100%;height:8px;border-radius:4px;margin:8px 0;
       appearance:none;-webkit-appearance:none}
#fprog::-webkit-progress-bar{background:#dde5ef;border-radius:4px}
#fprog::-webkit-progress-value{background:var(--cacc);border-radius:4px}
#fpct{font-size:12px;font-weight:700;color:var(--cacc)}

/* ── Status bar ── */
#sbar{background:#243546;color:#b0c4d8;font-size:11px;padding:3px 12px;
      flex-shrink:0;min-height:22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
</style>
</head>
<body>

<div id="hdr">
  <h1>reSpeaker XVF3800</h1>
  <span id="cdot">●</span>
  <span id="clbl">Disconnected</span>
  <button class="hbtn accent" onclick="apiConnect()">Connect</button>
  <button class="hbtn" onclick="apiDisconnect()">Disconnect</button>
  <button class="hbtn" onclick="refreshAll()">Refresh All</button>
  <label id="autolbl"><input type="checkbox" id="autocb" onchange="toggleAuto()"> Auto-refresh Live</label>
  <span id="sp"></span>
  <button class="hbtn green" onclick="saveConfig()">Save Config</button>
</div>
<div id="tabs"></div>
<div id="content"></div>
<div id="sbar">Ready.</div>

<script>
const GROUPS=[
  ["Firmware", ["VERSION","BLD_MSG","BLD_HOST","BLD_REPO_HASH","BLD_MODIFIED","BOOT_STATUS","USB_BIT_DEPTH"]],
  ["Live",     ["DOA_VALUE","AEC_AZIMUTH_VALUES","AEC_SPENERGY_VALUES","AUDIO_MGR_SELECTED_AZIMUTHS",
                "AEC_AECPATHCHANGE","AEC_AECCONVERGED","AEC_RT60","AEC_CURRENT_IDLE_TIME","AEC_MIN_IDLE_TIME",
                "PP_CURRENT_IDLE_TIME","PP_MIN_IDLE_TIME","AUDIO_MGR_CURRENT_IDLE_TIME","AUDIO_MGR_MIN_IDLE_TIME",
                "I2S_CURRENT_IDLE_TIME","I2S_MIN_IDLE_TIME","I2S_INACTIVE"]],
  ["Audio",    ["AUDIO_MGR_MIC_GAIN","AUDIO_MGR_REF_GAIN","AUDIO_MGR_SYS_DELAY","AUDIO_MGR_OP_L","AUDIO_MGR_OP_R",
                "AUDIO_MGR_SELECTED_CHANNELS","AUDIO_MGR_OP_PACKED","AUDIO_MGR_OP_UPSAMPLE",
                "AUDIO_MGR_FAR_END_DSP_ENABLE","I2S_DAC_DSP_ENABLE","I2S_INPUT_PACKED"]],
  ["AEC",      ["AEC_NUM_MICS","AEC_NUM_FARENDS","AEC_MIC_ARRAY_TYPE","AEC_MIC_ARRAY_GEO","SHF_BYPASS",
                "AEC_HPFONOFF","AEC_AECSILENCELEVEL","AEC_AECEMPHASISONOFF","AEC_FAR_EXTGAIN",
                "AEC_PCD_COUPLINGI","AEC_PCD_MINTHR","AEC_PCD_MAXTHR","AEC_ASROUTONOFF","AEC_ASROUTGAIN",
                "AEC_FIXEDBEAMSONOFF","AEC_FIXEDBEAMSAZIMUTH_VALUES","AEC_FIXEDBEAMSELEVATION_VALUES",
                "AEC_FIXEDBEAMSGATING","AEC_FIXEDBEAMNOISETHR"]],
  ["PostProc", ["PP_AGCONOFF","PP_AGCMAXGAIN","PP_AGCDESIREDLEVEL","PP_AGCGAIN","PP_AGCTIME","PP_AGCFASTTIME",
                "PP_AGCALPHAFASTGAIN","PP_AGCALPHASLOW","PP_AGCALPHAFAST","PP_LIMITONOFF","PP_LIMITPLIMIT",
                "PP_MIN_NS","PP_MIN_NN","PP_ECHOONOFF","PP_GAMMA_E","PP_GAMMA_ETAIL","PP_GAMMA_ENL",
                "PP_NLATTENONOFF","PP_NLAEC_MODE","PP_MGSCALE","PP_FMIN_SPEINDEX","PP_DTSENSITIVE",
                "PP_ATTNS_MODE","PP_ATTNS_NOMINAL","PP_ATTNS_SLOPE"]],
  ["LED",      ["LED_EFFECT","LED_BRIGHTNESS","LED_GAMMIFY","LED_SPEED","LED_COLOR","LED_DOA_COLOR","LED_RING_COLOR"]],
  ["GPIO",     ["GPO_READ_VALUES","GPO_WRITE_VALUE","GPO_PORT_PIN_INDEX","GPO_PIN_ACTIVE_LEVEL","GPO_PIN_VAL"]],
  ["System",   ["SAVE_CONFIGURATION","CLEAR_CONFIGURATION","REBOOT","MAX_CONTROL_TIME","RESET_MAX_CONTROL_TIME",
                "AUDIO_MGR_RESET_MIN_IDLE_TIME","I2S_RESET_MIN_IDLE_TIME","AEC_RESET_MIN_IDLE_TIME",
                "PP_RESET_MIN_IDLE_TIME","AEC_FILTER_CMD_ABORT","PP_NL_MODEL_CMD_ABORT","PP_EQUALIZATION_CMD_ABORT"]],
  ["Record",   []],
  ["Flash",    []],
];
const CONFIRM={"SAVE_CONFIGURATION":"Save current configuration to flash?",
               "CLEAR_CONFIGURATION":"Clear ALL saved config and revert to factory defaults?\n(Takes effect after reboot)",
               "REBOOT":"Reboot the device?\nAll unsaved settings will be lost."};
const LIVE_SET=new Set(["DOA_VALUE","AEC_AZIMUTH_VALUES","AEC_SPENERGY_VALUES",
  "AUDIO_MGR_SELECTED_AZIMUTHS","AEC_AECPATHCHANGE","AEC_AECCONVERGED","AEC_RT60"]);

let PARAMS={}, connected=false, selFw=null, flashEvt=null;

// ── Init ──────────────────────────────────────────────────────────────────────
async function init(){
  PARAMS=await fetch('/api/params').then(r=>r.json());
  buildUI();
  const s=await fetch('/api/status').then(r=>r.json());
  setConn(s.connected);
  connectSSE();
}

function setStatus(msg){document.getElementById('sbar').textContent=msg}
function setConn(c){
  connected=c;
  document.getElementById('cdot').className=c?'ok':'';
  const l=document.getElementById('clbl');
  l.textContent=c?'Connected':'Disconnected'; l.className=c?'ok':'';
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

// ── SSE ───────────────────────────────────────────────────────────────────────
function connectSSE(){
  const es=new EventSource('/api/live');
  es.onmessage=e=>{
    const d=JSON.parse(e.data);
    if(d.type==='status') setConn(d.connected);
    else if(d.type==='live') onLive(d.params);
  };
  es.onerror=()=>setTimeout(connectSSE,3000);
}

function onLive(params){
  for(const [name,info] of Object.entries(params)){
    setVal(name, info.fmt, true);
    if(name==='DOA_VALUE') updateDoa(info.raw);
    else if(name==='AEC_AZIMUTH_VALUES') setElem('beam-auto', info.raw.length>=4?toDeg(info.raw[3])+'°':'—');
    else if(name==='AEC_SPENERGY_VALUES') setElem('spenergy', info.raw.length>=4?info.raw[3].toFixed(0):'—');
    else if(name==='AEC_AECCONVERGED') setElem('aec-conv', info.raw[0]?'YES':'NO');
    else if(name==='AEC_RT60') setElem('rt60', info.fmt);
  }
}

function toDeg(rad){return (rad*180/Math.PI).toFixed(1)}
function setElem(id,v){const e=document.getElementById(id);if(e)e.textContent=v}
function setVal(name,txt,ok){
  const el=document.getElementById('v-'+name);
  if(!el) return;
  el.textContent=txt; el.className='pv'+(ok?' ok':ok===false?' er':'');
}

// ── Build UI ──────────────────────────────────────────────────────────────────
function buildUI(){
  const tabs=document.getElementById('tabs');
  const cont=document.getElementById('content');
  GROUPS.forEach(([name,plist],i)=>{
    const btn=document.createElement('button');
    btn.className='tbtn'+(i===0?' active':'');
    btn.textContent=name; btn.onclick=()=>switchTab(i);
    tabs.appendChild(btn);
    const pane=document.createElement('div');
    pane.className='pane'+(i===0?' active':'');
    pane.id='pane-'+i;
    if(name==='Flash') pane.appendChild(buildFlashPane());
    else if(name==='Record') pane.appendChild(buildRecordPane());
    else if(name==='Live') pane.appendChild(buildLivePane(plist));
    else pane.appendChild(buildParamPane(name,plist));
    cont.appendChild(pane);
  });
}

function switchTab(idx){
  document.querySelectorAll('.tbtn').forEach((b,i)=>b.classList.toggle('active',i===idx));
  document.querySelectorAll('.pane').forEach((p,i)=>p.classList.toggle('active',i===idx));
}

// ── Param pane ────────────────────────────────────────────────────────────────
function buildParamPane(gname, plist){
  const wrap=document.createElement('div');
  const tb=document.createElement('div'); tb.className='tbar';
  const rb=document.createElement('button'); rb.className='xbtn accent';
  rb.textContent='Refresh '+gname; rb.onclick=()=>refreshGroup(plist);
  tb.appendChild(rb); wrap.appendChild(tb);
  wrap.appendChild(buildTable(plist));
  return wrap;
}

function buildTable(plist){
  const tbl=document.createElement('table'); tbl.className='ptbl';
  tbl.innerHTML='<thead><tr><th>Parameter</th><th>Value</th><th>Input</th><th>Actions</th><th>Description</th></tr></thead>';
  const tb=document.createElement('tbody');
  plist.forEach(name=>{
    const p=PARAMS[name]; if(!p) return;
    const tr=document.createElement('tr');
    const badgeCls={'ro':'bro','rw':'brw','wo':'bwo'}[p.access]||'bro';
    let inp='', btns='<div class="pb">';
    if(p.access==='rw'||p.access==='wo')
      inp=`<input class="pe" id="e-${name}" type="text" placeholder="${p.count} val">`;
    if(p.access==='ro'||p.access==='rw')
      btns+=`<button class="rb" onclick="readOne('${name}')">Read</button>`;
    if(p.access==='rw'||p.access==='wo')
      btns+=`<button class="wb" onclick="writeOne('${name}')">Write</button>`;
    btns+='</div>';
    tr.innerHTML=`<td class="pn">${esc(name)} <span class="${badgeCls}">${p.access}</span></td>
      <td class="pv" id="v-${name}">—</td><td>${inp}</td><td>${btns}</td>
      <td class="pd" title="${esc(p.desc)}">${esc(p.desc)}</td>`;
    tb.appendChild(tr);
  });
  tbl.appendChild(tb); return tbl;
}

// ── Live pane (compass + table) ───────────────────────────────────────────────
function buildLivePane(plist){
  const wrap=document.createElement('div');
  wrap.innerHTML=`<div id="cpanel">
    <div><h3>Direction of Arrival</h3>
      <canvas id="dcanv" width="210" height="210"></canvas></div>
    <div class="cstats">
      <span class="sl">DoA Angle</span><span class="sv" id="doaang">—°</span>
      <span class="sl">Speech</span><span class="sv" id="doasp">—</span>
      <span class="sl">Auto-beam Az.</span><span class="sv" id="beam-auto">—</span>
      <span class="sl">Speech Energy</span><span class="sv" id="spenergy">—</span>
      <span class="sl">AEC Converged</span><span class="sv" id="aec-conv">—</span>
      <span class="sl">RT60</span><span class="sv" id="rt60">—</span>
    </div>
    <div style="display:flex;flex-direction:column;gap:6px;padding-top:20px">
      <button class="xbtn accent" onclick="refreshLive()">Refresh Live</button>
      <button class="xbtn" onclick="refreshAll()">Refresh All</button>
    </div>
  </div>`;
  const tb=document.createElement('div'); tb.className='tbar';
  const rb=document.createElement('button'); rb.className='xbtn accent';
  rb.textContent='Refresh Live'; rb.onclick=refreshLive; tb.appendChild(rb);
  wrap.appendChild(tb); wrap.appendChild(buildTable(plist));
  requestAnimationFrame(drawCompassBg);
  return wrap;
}

// ── Compass drawing ───────────────────────────────────────────────────────────
function drawCompassBg(){
  const c=document.getElementById('dcanv'); if(!c) return;
  const ctx=c.getContext('2d'), cx=105,cy=105,r=92;
  ctx.clearRect(0,0,210,210);
  ctx.beginPath(); ctx.arc(cx,cy,r,0,2*Math.PI);
  ctx.fillStyle='#f9fbfd'; ctx.fill();
  ctx.strokeStyle='#cdd4db'; ctx.lineWidth=2; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx,cy,8,0,2*Math.PI);
  ctx.fillStyle='#e8ecf0'; ctx.fill(); ctx.strokeStyle='#cdd4db'; ctx.lineWidth=1; ctx.stroke();
  for(let deg=0;deg<360;deg+=10){
    const rad=deg*Math.PI/180-Math.PI/2, major=deg%30===0;
    const ir=r-(major?14:6);
    ctx.beginPath();
    ctx.moveTo(cx+ir*Math.cos(rad),cy+ir*Math.sin(rad));
    ctx.lineTo(cx+r*Math.cos(rad),cy+r*Math.sin(rad));
    ctx.strokeStyle=major?'#aaa':'#ddd'; ctx.lineWidth=major?2:1; ctx.stroke();
    if(major){
      ctx.font='9px Helvetica'; ctx.fillStyle='#6b7785'; ctx.textAlign='center'; ctx.textBaseline='middle';
      const tx=cx+(r+14)*Math.cos(rad), ty=cy+(r+14)*Math.sin(rad);
      ctx.fillText(deg+'°',tx,ty);
    }
  }
}

function drawNeedle(angle, speech){
  const c=document.getElementById('dcanv'); if(!c) return;
  drawCompassBg();
  const ctx=c.getContext('2d'), cx=105,cy=105,r=92;
  const color=speech?'#e74c3c':'#2980b9';
  const rad=(angle-90)*Math.PI/180, nr=r-16;
  const nx=cx+nr*Math.cos(rad), ny=cy+nr*Math.sin(rad);
  ctx.save();
  ctx.strokeStyle='#ccc'; ctx.lineWidth=3;
  ctx.beginPath(); ctx.moveTo(cx+1,cy+1); ctx.lineTo(nx+1,ny+1); ctx.stroke();
  ctx.strokeStyle=color; ctx.lineWidth=3;
  ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(nx,ny); ctx.stroke();
  const headLen=12, headW=5, angle2=Math.atan2(ny-cy,nx-cx);
  ctx.beginPath();
  ctx.moveTo(nx,ny);
  ctx.lineTo(nx-headLen*Math.cos(angle2-0.4),ny-headLen*Math.sin(angle2-0.4));
  ctx.lineTo(nx-headLen*Math.cos(angle2+0.4),ny-headLen*Math.sin(angle2+0.4));
  ctx.closePath(); ctx.fillStyle=color; ctx.fill();
  ctx.beginPath(); ctx.arc(cx,cy,6,0,2*Math.PI);
  ctx.fillStyle=color; ctx.fill();
  ctx.strokeStyle='#fff'; ctx.lineWidth=2; ctx.stroke();
  ctx.restore();
}

function updateDoa(raw){
  if(!raw||raw.length<2) return;
  const ang=raw[0], speech=!!raw[1];
  drawNeedle(ang, speech);
  const a=document.getElementById('doaang');
  if(a){a.textContent=ang+'°'; a.style.color=speech?'#e74c3c':'#2980b9'}
  const s=document.getElementById('doasp');
  if(s){s.textContent=speech?'SPEECH':'Silence'; s.style.color=speech?'#e74c3c':'#6b7785'}
}

// ── Record pane ───────────────────────────────────────────────────────────────
let _recPollTimer=null;

function buildRecordPane(){
  const d=document.createElement('div');
  d.innerHTML=`
  <div class="fcard">
    <h3>Audio Recording  <span style="font-size:11px;font-weight:400;color:#6b7785">(saves to server filesystem)</span></h3>
    <div style="display:grid;grid-template-columns:140px 1fr;gap:7px 12px;align-items:center;font-size:12px;margin-bottom:12px">
      <span style="color:#6b7785">Device:</span>
      <span id="rec-dev" style="font-family:monospace">auto-detect…</span>
      <span style="color:#6b7785">Channels:</span>
      <span id="rec-ch" style="font-weight:700;color:#2980b9">—</span>
      <span style="color:#6b7785">Sample rate:</span>
      <span id="rec-sr">—</span>
      <span style="color:#6b7785">Segment length:</span>
      <span><input class="pe" id="rec-seg" type="number" value="60" min="5" max="3600" style="width:80px"> seconds (new folder every segment)</span>
      <span style="color:#6b7785">Output folder:</span>
      <input class="pe" id="rec-out" type="text" value="" placeholder="~/respeaker_recordings (default)" style="width:340px">
    </div>
    <div class="tbar">
      <button class="xbtn ok" id="recstart" onclick="recStart()">Start Recording</button>
      <button class="xbtn" id="recstop" onclick="recStop()" disabled>Stop</button>
      <button class="xbtn" onclick="loadAudioDevices()">Re-scan device</button>
      <span id="rec-status" style="font-size:12px;color:#6b7785;margin-left:14px;font-weight:600">Idle</span>
    </div>
  </div>
  <div class="fcard">
    <h3>Recordings  <span style="font-size:11px;font-weight:400;color:#6b7785">— folder <span id="rec-out-disp" style="font-family:monospace">—</span></span></h3>
    <ul class="fwlist" id="reclist"><li style="color:#6b7785;font-size:12px">Loading…</li></ul>
    <button class="xbtn" onclick="loadRecList()" style="margin-top:8px">Refresh</button>
  </div>`;
  loadAudioDevices();
  loadRecList();
  startRecStatusPoll();
  return d;
}

async function loadAudioDevices(){
  const r=await fetch('/api/audio/devices').then(r=>r.json()).catch(e=>({ok:false,msg:String(e)}));
  const dn=document.getElementById('rec-dev'), ch=document.getElementById('rec-ch'), sr=document.getElementById('rec-sr');
  if(!r.ok){ if(dn) dn.textContent='ERROR: '+r.msg; return; }
  if(r.detected){
    if(dn) dn.textContent=r.detected.name+'  [idx '+r.detected.idx+']';
    if(ch) ch.textContent=r.detected.channels+' ch';
    if(sr) sr.textContent=r.detected.samplerate+' Hz';
  } else {
    if(dn) dn.textContent='No ReSpeaker input found — plug in the mic';
    if(ch) ch.textContent='—'; if(sr) sr.textContent='—';
  }
}

async function recStart(){
  const seg=parseInt(document.getElementById('rec-seg').value)||60;
  const out=document.getElementById('rec-out').value.trim();
  const body={segment:seg};
  if(out) body.outdir=out;
  const r=await fetch('/api/audio/start',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
  if(!r.ok){alert('Start failed: '+r.msg); return}
  document.getElementById('recstart').disabled=true;
  document.getElementById('recstop').disabled=false;
  setStatus('Recording started: '+(r.info?.device_name||''));
}

async function recStop(){
  const r=await fetch('/api/audio/stop',{method:'POST'}).then(r=>r.json());
  document.getElementById('recstart').disabled=false;
  document.getElementById('recstop').disabled=true;
  setStatus('Recording stopped — '+(r.segments||0)+' segment(s) saved');
  loadRecList();
}

function startRecStatusPoll(){
  if(_recPollTimer) clearInterval(_recPollTimer);
  _recPollTimer=setInterval(async()=>{
    const el=document.getElementById('rec-status');
    if(!el){clearInterval(_recPollTimer); _recPollTimer=null; return}
    const r=await fetch('/api/audio/status').then(r=>r.json()).catch(()=>null);
    if(!r) return;
    const outDisp=document.getElementById('rec-out-disp');
    if(outDisp&&r.info&&r.info.outdir) outDisp.textContent=r.info.outdir;
    if(r.active){
      const e=r.elapsed||0, m=Math.floor(e/60), s=Math.floor(e%60);
      el.textContent=`Recording  ${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}  •  ${r.info.segments_saved} segment(s) saved`;
      el.style.color='#e74c3c';
      const sb=document.getElementById('recstart'), tb=document.getElementById('recstop');
      if(sb) sb.disabled=true; if(tb) tb.disabled=false;
    } else {
      el.textContent='Idle';
      el.style.color='#6b7785';
    }
  },1000);
}

async function loadRecList(){
  const ul=document.getElementById('reclist'); if(!ul) return;
  const r=await fetch('/api/recordings').then(r=>r.json()).catch(()=>null);
  if(!r){ul.innerHTML='<li style="color:#e74c3c;font-size:12px">Failed to load.</li>'; return}
  const od=document.getElementById('rec-out-disp'); if(od) od.textContent=r.outdir||'—';
  if(!r.folders.length){ul.innerHTML='<li style="color:#6b7785;font-size:12px">No recordings yet.</li>'; return}
  ul.innerHTML='';
  r.folders.forEach(f=>{
    const li=document.createElement('li'); li.className='fwitem';
    const mb=(f.size/1024/1024).toFixed(2);
    li.innerHTML=`<span class="fwkind">${f.channels}ch</span>
      <span style="font-family:monospace;font-size:12px;font-weight:600">${esc(f.name)}</span>
      <span class="fwn">${mb} MB</span>
      <span class="fwn" style="margin-left:auto;opacity:0.7">${esc(f.path)}</span>`;
    ul.appendChild(li);
  });
}

// ── Flash pane ────────────────────────────────────────────────────────────────
function buildFlashPane(){
  const d=document.createElement('div');
  d.innerHTML=`
  <div class="fcard">
    <h3>Firmware Files  <span style="font-size:11px;font-weight:400;color:#6b7785">(from xmos_firmwares/)</span></h3>
    <ul class="fwlist" id="fwlist"><li style="color:#6b7785;font-size:12px">Loading...</li></ul>
  </div>
  <div class="fcard">
    <h3>Flash</h3>
    <div style="font-size:12px;color:#6b7785;margin-bottom:10px">
      Enter DFU mode first: hold Mute button + plug USB → LED flashes red
    </div>
    <div class="tbar">
      <button class="xbtn" onclick="scanDfu()">Scan DFU Devices</button>
      <button class="xbtn accent" id="flashbtn" onclick="startFlash()">Flash Selected</button>
      <span id="fpct"></span>
    </div>
    <progress id="fprog" value="0" max="100"></progress>
    <div id="flog"></div>
  </div>`;
  loadFwList();
  return d;
}

async function loadFwList(){
  const ul=document.getElementById('fwlist'); if(!ul) return;
  const files=await fetch('/api/firmware/list').then(r=>r.json());
  ul.innerHTML='';
  if(!files.length){ul.innerHTML='<li style="color:#6b7785;font-size:12px">No .bin files found in xmos_firmwares/</li>'; return}
  files.forEach(f=>{
    const li=document.createElement('li'); li.className='fwitem';
    const kind=f.label.split(' ')[0];
    const kindCls=kind==='RECOVER'?'fwkind rec':'fwkind';
    li.innerHTML=`<span class="${kindCls}">${esc(kind)}</span>
      <span style="font-size:12px;font-weight:600">${esc(f.label)}</span>
      <span class="fwn">${esc(f.name)}</span>`;
    li.onclick=()=>{
      document.querySelectorAll('.fwitem').forEach(x=>x.classList.remove('sel'));
      li.classList.add('sel'); selFw=f.path;
      setStatus('Selected: '+f.name);
    };
    ul.appendChild(li);
  });
}

async function scanDfu(){
  setStatus('Scanning DFU devices…');
  try{
    const r=await fetch('/api/read/VERSION').then(r=>r.json());
    if(r.ok) setStatus('Device in normal mode (not DFU). Enter DFU mode first.');
    else setStatus('Normal device not connected — may already be in DFU mode.');
  } catch(e){ setStatus('Scan error: '+e) }
}

function startFlash(){
  if(!selFw){alert('Select a firmware file first.'); return}
  if(!confirm('Flash firmware?\n\nFile: '+selFw.split('/').pop()+'\n\nDO NOT disconnect USB during flash.')) return;
  const log=document.getElementById('flog');
  const prog=document.getElementById('fprog');
  const pct=document.getElementById('fpct');
  log.textContent=''; prog.value=0; pct.textContent='';
  document.getElementById('flashbtn').disabled=true;
  if(flashEvt){flashEvt.close(); flashEvt=null}

  fetch('/api/firmware/flash',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path:selFw})}).then(resp=>{
    const reader=resp.body.getReader(), dec=new TextDecoder();
    let buf='';
    function pump(){
      reader.read().then(({done,value})=>{
        if(done){document.getElementById('flashbtn').disabled=false; return}
        buf+=dec.decode(value,{stream:true});
        let idx;
        while((idx=buf.indexOf('\n\n'))!==-1){
          const line=buf.slice(0,idx).trim(); buf=buf.slice(idx+2);
          if(!line.startsWith('data:')) continue;
          try{
            const d=JSON.parse(line.slice(5).trim());
            if(d.type==='log'){
              log.textContent+=d.text+'\n';
              log.scrollTop=log.scrollHeight;
              if(d.pct!=null){prog.value=d.pct; pct.textContent=d.pct+'%'}
            } else if(d.type==='done'){
              if(d.ok){prog.value=100; pct.textContent='100%'; setStatus('Flash complete! Reconnect device.');}
              else {setStatus('Flash failed (code '+d.rc+'). Check log.');}
              document.getElementById('flashbtn').disabled=false;
            }
          } catch(e){}
        }
        pump();
      });
    }
    pump();
  });
}

// ── Read / Write ──────────────────────────────────────────────────────────────
async function readOne(name){
  setStatus('Reading '+name+'…');
  const r=await fetch('/api/read/'+name).then(r=>r.json());
  if(r.ok){setVal(name,r.formatted,true); setStatus(name+' = '+r.formatted);}
  else{setVal(name,'['+r.msg+']',false); setStatus('Error: '+r.msg);}
}

async function writeOne(name){
  const entry=document.getElementById('e-'+name);
  const val=entry?entry.value.trim():'';
  if(!val){alert('Enter a value first.'); return}
  if(CONFIRM[name]&&!confirm(CONFIRM[name])) return;
  setStatus('Writing '+name+'…');
  const r=await fetch('/api/write/'+name,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({value:val})}).then(r=>r.json());
  if(r.ok){
    if(r.readback!=null) setVal(name,r.readback,true);
    setStatus('Wrote '+name+(r.readback?' = '+r.readback:''));
  } else {setStatus('Error writing '+name+': '+r.msg);}
}

async function refreshGroup(plist){
  if(!connected){setStatus('Not connected.'); return}
  for(const name of plist){
    if(!PARAMS[name]) continue;
    const acc=PARAMS[name].access;
    if(acc==='ro'||acc==='rw'){
      const r=await fetch('/api/read/'+name).then(r=>r.json());
      if(r.ok) setVal(name,r.formatted,true);
      else setVal(name,'[err]',false);
    }
  }
  setStatus('Group refreshed.');
}

async function refreshLive(){
  const liveParams=GROUPS.find(g=>g[0]==='Live')?.[1]||[];
  await refreshGroup(liveParams);
}

async function refreshAll(){
  for(const [,plist] of GROUPS) if(plist.length) await refreshGroup(plist);
}

// ── Auto-refresh ──────────────────────────────────────────────────────────────
let _autoTimer=null;
function toggleAuto(){
  const on=document.getElementById('autocb').checked;
  clearInterval(_autoTimer); _autoTimer=null;
  if(on) _autoTimer=setInterval(refreshLive, 1500);
}

// ── System actions ────────────────────────────────────────────────────────────
async function apiConnect(){
  setStatus('Connecting…');
  const r=await fetch('/api/connect',{method:'POST'}).then(r=>r.json());
  setStatus(r.ok?'Connected.':'Connect failed: '+r.msg);
  if(r.ok) setConn(true);
}

async function apiDisconnect(){
  await fetch('/api/disconnect',{method:'POST'});
  setConn(false); setStatus('Disconnected.');
}

async function saveConfig(){
  if(!confirm('Save current configuration to flash?')) return;
  const r=await fetch('/api/write/SAVE_CONFIGURATION',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({value:'1'})}).then(r=>r.json());
  setStatus(r.ok?'Configuration saved.':'Save failed: '+r.msg);
}

// ── Start ─────────────────────────────────────────────────────────────────────
init();
</script>
</body>
</html>
"""

# ── Entry point ───────────────────────────────────────────────────────────────

def _find_free_port(host, preferred, low=1, high=9999):
    """Try `preferred` port first, then scan [low..high] for any free port."""
    bind_host = "" if host in ("0.0.0.0", "") else host

    def _try(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((bind_host, port))
                return True
            except OSError:
                return False

    if low <= preferred <= high and _try(preferred):
        return preferred
    # Scan upward from preferred+1 first (likely closer to user's intent)
    for port in range(max(preferred + 1, low), high + 1):
        if _try(port):
            return port
    # Then scan downward from preferred-1
    for port in range(min(preferred - 1, high), low - 1, -1):
        if _try(port):
            return port
    return None


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="reSpeaker XVF3800 Web Control Panel")
    p.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    p.add_argument("--port", type=int, default=5000, help="Preferred port (default: 5000)")
    p.add_argument("--strict-port", action="store_true",
                   help="Fail if --port is busy instead of auto-picking a free port in 1..9999")
    args = p.parse_args()

    if args.strict_port:
        chosen_port = args.port
    else:
        chosen_port = _find_free_port(args.host, args.port, low=1, high=9999)
        if chosen_port is None:
            print(f"ERROR: no free TCP port found in [1..9999]")
            sys.exit(1)
        if chosen_port != args.port:
            print(f"  Note: port {args.port} busy → auto-picked {chosen_port}")

    print(f"\n  reSpeaker XVF3800 Web Control Panel")
    print(f"  Open:  http://localhost:{chosen_port}   (or http://<this-machine-ip>:{chosen_port})\n")
    app.run(host=args.host, port=chosen_port, threaded=True, use_reloader=False)
