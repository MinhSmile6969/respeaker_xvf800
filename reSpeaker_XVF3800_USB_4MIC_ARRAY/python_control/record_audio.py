#!/usr/bin/env python3
"""Continuous multi-channel recorder for reSpeaker XVF3800.

Auto-detects active firmware's channel count (2 or 6) and saves one WAV
per channel into a new timestamped folder every minute.

Usage:
    python record_audio.py                       # default: 60 s segments, ~/respeaker_recordings
    python record_audio.py --segment 30          # 30 s segments
    python record_audio.py --outdir /tmp/mic     # custom output folder
    python record_audio.py --device 5            # force PortAudio device index
"""

import argparse
import os
import sys
import threading
import time
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf


def find_respeaker_device():
    """Return (index, name, max_channels, default_samplerate) for the ReSpeaker mic."""
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] <= 0:
            continue
        name = dev["name"].lower()
        if "respeaker" in name or "xvf" in name or "seeed" in name:
            return idx, dev["name"], dev["max_input_channels"], int(dev.get("default_samplerate", 16000))
    return None


def save_segment(chunks, channels, samplerate, outdir):
    """Save each channel of `chunks` as its own WAV inside a new timestamped folder."""
    if not chunks:
        return None
    data = np.concatenate(chunks, axis=0)  # shape: (frames, channels)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = os.path.join(outdir, ts)
    os.makedirs(folder, exist_ok=True)
    for ch in range(channels):
        path = os.path.join(folder, f"ch{ch}.wav")
        sf.write(path, data[:, ch].astype("float32"), samplerate, subtype="PCM_16")
    duration = len(data) / samplerate
    print(f"  [{ts}]  saved {channels}ch × {duration:.1f}s  →  {folder}")
    return folder


def main():
    ap = argparse.ArgumentParser(description="reSpeaker XVF3800 continuous recorder")
    ap.add_argument("--segment", type=int, default=60, help="Segment length in seconds (default 60)")
    ap.add_argument("--outdir",  default=os.path.expanduser("~/respeaker_recordings"),
                    help="Output directory (default ~/respeaker_recordings)")
    ap.add_argument("--device",  type=int, default=None, help="Force PortAudio device index")
    ap.add_argument("--rate",    type=int, default=None, help="Force sample rate")
    args = ap.parse_args()

    # ── Device detection ───────────────────────────────────────────────────
    if args.device is not None:
        info = sd.query_devices(args.device)
        dev_idx, dev_name = args.device, info["name"]
        max_ch = info["max_input_channels"]
        sr_default = int(info.get("default_samplerate", 16000))
    else:
        found = find_respeaker_device()
        if not found:
            print("ERROR: no reSpeaker / XVF / Seeed input device detected.")
            print("Plug in the mic, or pass --device <idx>. List devices with:")
            print("    python -c 'import sounddevice as sd; print(sd.query_devices())'")
            sys.exit(1)
        dev_idx, dev_name, max_ch, sr_default = found

    sr = args.rate or sr_default
    os.makedirs(args.outdir, exist_ok=True)

    print(f"\n  Device:       [{dev_idx}] {dev_name}")
    print(f"  Channels:     {max_ch}  (auto-detected from active firmware)")
    print(f"  Sample rate:  {sr} Hz")
    print(f"  Segment:      {args.segment} s")
    print(f"  Output dir:   {args.outdir}\n")

    # ── Recording state (thread-safe rotation) ─────────────────────────────
    buf_lock = threading.Lock()
    buffer = []

    def callback(indata, frames, time_info, status):
        if status:
            print(f"  [stream status] {status}", file=sys.stderr)
        with buf_lock:
            buffer.append(indata.copy())

    # ── Open stream and rotate every N seconds ─────────────────────────────
    stream = sd.InputStream(
        device=dev_idx, channels=max_ch, samplerate=float(sr),
        dtype="float32", callback=callback, blocksize=1024,
    )
    print(f"  Recording... (Ctrl+C to stop)\n")
    try:
        with stream:
            while True:
                time.sleep(args.segment)
                with buf_lock:
                    chunks, buffer[:] = buffer[:], []
                # save in background so we don't drop audio while writing
                threading.Thread(
                    target=save_segment,
                    args=(chunks, max_ch, sr, args.outdir),
                    daemon=False,
                ).start()
    except KeyboardInterrupt:
        print("\n  Stopping...")
        with buf_lock:
            tail = buffer[:]
            buffer.clear()
        if tail:
            save_segment(tail, max_ch, sr, args.outdir)
        print("  Done.")


if __name__ == "__main__":
    main()
