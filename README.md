# reSpeaker XVF3800 — Control Panel

Tools for monitoring, controlling, and flashing firmware on the **reSpeaker XVF3800 USB 4-Mic Array**.

This repo ships **two files**:

| File | Description |
|------|-------------|
| `respeaker_ui.py` | Desktop GUI (Tkinter) — run locally on the machine with the mic |
| `respeaker_web.py` | Web UI (Flask) — SSH into the machine, open in any browser remotely |

Both files must be placed inside the SDK's `python_control/` folder (see [Setup](#setup)).

---

## Features

| Tab / Section | Description |
|---------------|-------------|
| **Firmware** | Read version, build info, boot status |
| **Live** | Real-time DOA compass, AEC energy, speech activity — auto-refreshes every 1.5 s |
| **Audio** | Mic/reference gain, output channels, I²S config |
| **AEC** | Echo cancellation parameters (including System Delay) |
| **PostProc** | AGC, noise suppression, limiter, de-reverberation |
| **LED** | Effect, brightness, colour, DOA ring |
| **GPIO** | Read/write GPIO port pins |
| **System** | Save / clear config, reboot |
| **Flash** | Flash `.bin` firmware files from `xmos_firmwares/` via USB DFU |
| **Record** | Capture audio from the device (`respeaker_ui.py` only) |

---

## Requirements

### Desktop GUI — `respeaker_ui.py`

```bash
sudo apt install python3-tk libusb-1.0-0 dfu-util
pip install pyusb sounddevice soundfile numpy libusb-package
```

### Web UI — `respeaker_web.py`

```bash
sudo apt install libusb-1.0-0 dfu-util
pip install flask pyusb libusb-package
```

> No display or X11 required for the web UI — works over plain SSH.

---

## USB Permissions Setup

> **Do this once on every machine where the mic is connected.**  
> Without it, both tools will fail to connect and `dfu-util` will not detect the device.

### Step 1 — Create udev rules

Covers both **normal mode** (control panel) and **DFU mode** (firmware flashing):

```bash
sudo tee /etc/udev/rules.d/99-respeaker.rules > /dev/null << 'EOF'
# ReSpeaker XVF3800 — normal operation mode (VID 2886, PID 001A)
SUBSYSTEM=="usb", ATTR{idVendor}=="2886", ATTR{idProduct}=="001a", MODE="0666", GROUP="plugdev"
# ReSpeaker XVF3800 — DFU / bootloader mode (same VID, PID may vary)
SUBSYSTEM=="usb", ATTR{idVendor}=="2886", MODE="0666", GROUP="plugdev"
EOF
```

### Step 2 — Add user to `plugdev` group

```bash
sudo usermod -aG plugdev $USER
```

> Log out and log back in (or reboot) for group membership to take effect.

### Step 3 — Reload udev

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Step 4 — Verify

```bash
lsusb | grep 2886
```

Expected:
```
Bus 001 Device 005: ID 2886:001a Seeed Technology Co., Ltd ReSpeaker XVF3800 4-Mic Array
```

> **Still getting `Permission denied`?** Run `groups` — confirm `plugdev` is listed. If not, reboot.

---

## Setup

### Step 1 — Download the official SDK

```bash
git clone https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY.git
```

Structure after clone:

```
reSpeaker_XVF3800_USB_4MIC_ARRAY/
├── python_control/
│   ├── xvf_host.py          ← required by both UI files
│   ├── respeaker_get_doa.py
│   └── readme.md
├── xmos_firmwares/
│   ├── usb/
│   ├── i2s/
│   └── recover/
├── host_control/
└── README.md
```

### Step 2 — Copy UI files into the SDK

```bash
cp respeaker_ui.py  reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control/
cp respeaker_web.py reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control/
```

After this step:

```
reSpeaker_XVF3800_USB_4MIC_ARRAY/
└── python_control/
    ├── xvf_host.py          ← SDK (required)
    ├── respeaker_get_doa.py ← SDK
    ├── respeaker_ui.py      ← copied from this repo  ✓
    ├── respeaker_web.py     ← copied from this repo  ✓
    └── readme.md
```

> Both files import `xvf_host.py` at runtime. They also look for `../xmos_firmwares/` for firmware flashing.

---

## Run — Desktop GUI

Requires a display (monitor, X11 forwarding, or VNC).

```bash
cd reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control
python3 respeaker_ui.py
```

Plug in the device via USB before launching, then click **Connect**.

---

## Run — Web UI (via SSH, no display needed)

```bash
# On the machine where the mic is connected:
cd reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control
python3 respeaker_web.py              # default port 5000
python3 respeaker_web.py --port 8080  # custom port
```

Then open a browser on **any machine** on the same network:

```
http://<host-ip>:5000
```

The web UI includes all parameter tabs, real-time DOA compass, firmware flash with progress log, and Save Config — everything except audio recording.

---

## Running on NVIDIA Jetson AGX

Jetson AGX (Xavier / Orin) runs Ubuntu ARM64 — all steps above apply. Extra notes:

### Install dependencies

```bash
sudo apt install python3-tk libusb-1.0-0 dfu-util
pip3 install pyusb libusb-package flask sounddevice soundfile numpy
```

### Display options for the Desktop GUI

#### Option A — Direct HDMI/DP monitor

No extra config needed:

```bash
python3 respeaker_ui.py
```

#### Option B — SSH with X11 forwarding

From your laptop:

```bash
ssh -X user@<jetson-ip>
cd reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control
python3 respeaker_ui.py
```

> Requires an X server on your laptop:  
> **Linux** — built-in | **Windows** — [VcXsrv](https://sourceforge.net/projects/vcxsrv/) | **macOS** — [XQuartz](https://www.xquartz.org/)

#### Option C — Headless (recommended: use Web UI instead)

The web UI is the simplest solution for headless Jetson — no VNC needed:

```bash
python3 respeaker_web.py --port 5000
# open http://<jetson-ip>:5000 from your laptop browser
```

---

## Flashing Firmware Through the UI

Both UIs can flash firmware. The device must be in **DFU mode** first.

### Enter DFU mode

1. Unplug the device.
2. Hold the **Mute button**, plug USB back in, keep holding **~3–5 s** until LED flashes red.
3. Release — device is now in DFU mode.

### Flash workflow

```
Hold Mute + plug USB → LED flashes red
         ↓
UI: Flash tab → select firmware → Flash Selected Firmware → wait 100%
         ↓
Device reboots → unplug & replug → Connect
```

### Firmware files

| Mode | File path |
|------|-----------|
| **USB v2.0.7** (recommended) | `xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.7.bin` |
| USB 6-ch v2.0.8 | `xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_6chl_v2.0.8.bin` |
| USB v2.0.6 | `xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.6.bin` |
| USB v2.0.5 | `xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.5.bin` |
| I2S Master v1.0.7 48kHz | `xmos_firmwares/i2s/respeaker_xvf3800_i2s_master_dfu_firmware_v1.0.7_48k_test5.bin` |
| I2S Master v1.0.5 48kHz | `xmos_firmwares/i2s/respeaker_xvf3800_i2s_master_dfu_firmware_v1.0.5_48k.bin` |
| I2S v1.0.4 | `xmos_firmwares/i2s/respeaker_xvf3800_i2s_dfu_firmware_v1.0.4.bin` |
| **RECOVER (erase)** | `xmos_firmwares/recover/4mb_all_ff.bin` |

### Flash from command line (without UI)

```bash
sudo dfu-util -R -e -a 1 -D reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.7.bin
```

### Flash errors

| Message | Cause | Fix |
|---------|-------|-----|
| `Cannot open DFU device` | USB permission denied | Re-apply udev rules |
| `No DFU capable USB device available` | Not in DFU mode | Repeat Hold Mute + plug in |
| `dfu-util not found` | Tool missing | `sudo apt install dfu-util` |
| `error resetting after download` | Normal on some firmware | Ignore — flash succeeded |

---

## Device Recovery — Bricked / Not Detected After Flash

If the device is frozen (stuck LED, no USB detection) after a failed flash:

### Step 1 — Enter DFU mode

Hold Mute + plug in USB → hold ~3–5 s until LED flashes red.

### Step 2 — Verify DFU device visible

```bash
sudo dfu-util -l
```

Should show a device with Vendor ID `2886`. If not, repeat Step 1.

### Step 3 — Erase flash (recovery image)

File location: `reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/recover/4mb_all_ff.bin`

```bash
sudo dfu-util -R -e -a 1 -D reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/recover/4mb_all_ff.bin
```

> LED will go dark — this is expected.

### Step 4 — Flash desired firmware

See firmware table above. Example:

```bash
sudo dfu-util -R -e -a 1 -D reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.7.bin
```

### Step 5 — Reconnect normally

Unplug and replug **without** holding Mute. Device should boot normally.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: xvf_host` | File not inside `python_control/` — re-check Setup Step 2 |
| `No backend available` (pyusb) | `libusb` not installed: `sudo apt install libusb-1.0-0` |
| `Permission denied` on USB | Follow USB Permissions Setup section above |
| `_tkinter` not found | `sudo apt install python3-tk` |
| `ModuleNotFoundError: flask` | `pip install flask` |
| Firmware folder empty in Flash tab | `xmos_firmwares/` must be one level above `python_control/` |
| Web UI: `Address already in use` | Use `--port 8080` (or any free port) |
| `DISPLAY not set` (Jetson SSH) | Use Web UI instead, or `ssh -X` for X11 forwarding |
