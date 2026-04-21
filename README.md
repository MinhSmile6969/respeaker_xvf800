# reSpeaker XVF3800 — Control Panel GUI

A Python/Tkinter GUI for monitoring, controlling, and flashing firmware on the **reSpeaker XVF3800 USB 4-Mic Array**.

This repo ships **one file only**: `respeaker_ui.py`.  
It must be placed inside the official SDK folder (see [Setup](#setup) below).

---

## Features

| Tab | Description |
|-----|-------------|
| **Firmware** | Read version, build info, boot status |
| **Live** | Real-time DOA compass, AEC energy, speech activity — auto-refreshes every 1.5 s |
| **Audio** | Mic/reference gain, output channels, I²S config |
| **AEC** | Echo cancellation parameters |
| **PostProc** | AGC, noise suppression, limiter, de-reverberation |
| **LED** | Effect, brightness, colour, DOA ring |
| **GPIO** | Read/write GPIO port pins |
| **System** | Save / clear config, reboot |
| **Flash** | Flash `.bin` firmware files from `xmos_firmwares/` via USB DFU |
| **Record** | Capture audio from the device via PulseAudio |

---

## Requirements

| Dependency | Version |
|------------|---------|
| Python | 3.6 + |
| tkinter | bundled with Python (install `python3-tk` on Ubuntu if missing) |
| pyusb | `pip install pyusb` |
| libusb | system package — see below |

### Install system packages (Ubuntu/Debian)

```bash
sudo apt install python3-tk libusb-1.0-0
pip install pyusb
```

### Install system packages (Fedora/RHEL)

```bash
sudo dnf install python3-tkinter libusb1
pip install pyusb
```

---

## Setup

### Step 1 — Download the official SDK

Clone or download the SDK from the Seeed Studio GitHub repository:

```bash
git clone https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY.git
```

The resulting folder structure should look like this:

```
reSpeaker_XVF3800_USB_4MIC_ARRAY/
├── python_control/
│   ├── xvf_host.py          ← SDK file (required by the UI)
│   ├── respeaker_get_doa.py
│   └── readme.md
├── xmos_firmwares/
│   ├── usb/
│   ├── i2s/
│   └── recover/
├── host_control/
└── README.md
```

### Step 2 — Place `respeaker_ui.py` in the correct folder

Copy `respeaker_ui.py` into **`reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control/`**:

```bash
cp respeaker_ui.py reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control/
```

After this step the folder should be:

```
reSpeaker_XVF3800_USB_4MIC_ARRAY/
└── python_control/
    ├── xvf_host.py          ← already in SDK
    ├── respeaker_get_doa.py ← already in SDK
    ├── respeaker_ui.py      ← copied from this repo  ✓
    └── readme.md
```

> **Why this location?**  
> `respeaker_ui.py` imports `xvf_host.py` at runtime using a relative path.  
> Both files must be in the same `python_control/` directory.  
> The firmware flash feature also looks for `../xmos_firmwares/` relative to this folder.

---

## Run

```bash
cd reSpeaker_XVF3800_USB_4MIC_ARRAY/python_control
python3 respeaker_ui.py
```

Plug in the reSpeaker device via USB **before** launching, then click **Connect** in the UI.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: xvf_host` | `respeaker_ui.py` is not inside `python_control/` — re-check Step 2 |
| `No backend available` (pyusb) | `libusb` is not installed — run the apt/dnf command above |
| `Permission denied` on USB device | Add udev rule: `echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2886", MODE="0666"' \| sudo tee /etc/udev/rules.d/99-respeaker.rules && sudo udevadm control --reload` |
| `_tkinter` not found | Install `python3-tk`: `sudo apt install python3-tk` |
| Firmware folder empty in Flash tab | Ensure `xmos_firmwares/` exists one level above `python_control/` and contains `.bin` files |

---

## Device Recovery — Bricked / USB Not Detected After Flash

If the device becomes unresponsive (frozen LED, not detected by the OS) after a failed firmware flash, follow these steps to recover it via USB DFU mode.

### Prerequisites

```bash
sudo apt install dfu-util
```

### Step 1 — Enter DFU (bootloader) mode

1. **Unplug** the device from USB.
2. **Hold the Mute button** and **plug the USB cable back in** while keeping the button held.
3. Continue holding the Mute button for **~3–5 seconds** until the LED flashes red.
4. Release the button — the device is now in DFU mode.

### Step 2 — Verify the device is detected

```bash
sudo dfu-util -l
```

You should see a DFU device listed (Vendor ID `2886`). If nothing appears, repeat Step 1.

### Step 3 — Flash the recovery firmware (erase flash)

Use the `4mb_all_ff.bin` recovery image to wipe the flash.  
This file is located at:

```
reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/recover/4mb_all_ff.bin
```

```bash
sudo dfu-util -R -e -a 1 -D reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/recover/4mb_all_ff.bin
```

> This erases all firmware from the device. The LED will go dark or stay red — this is expected.

### Step 4 — Flash the desired firmware

Choose the appropriate firmware from the table below:

| Mode | File path |
|------|-----------|
| USB (recommended) v2.0.7 | `reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.7.bin` |
| USB 6-channel v2.0.8 | `reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_6chl_v2.0.8.bin` |
| USB v2.0.6 | `reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.6.bin` |
| USB v2.0.5 | `reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.5.bin` |
| I2S Master v1.0.7 48kHz | `reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/i2s/respeaker_xvf3800_i2s_master_dfu_firmware_v1.0.7_48k_test5.bin` |
| I2S Master v1.0.5 48kHz | `reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/i2s/respeaker_xvf3800_i2s_master_dfu_firmware_v1.0.5_48k.bin` |
| I2S v1.0.4 | `reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/i2s/respeaker_xvf3800_i2s_dfu_firmware_v1.0.4.bin` |

Example (USB v2.0.7):

```bash
sudo dfu-util -R -e -a 1 -D reSpeaker_XVF3800_USB_4MIC_ARRAY/xmos_firmwares/usb/respeaker_xvf3800_usb_dfu_firmware_v2.0.7.bin
```

### Step 5 — Verify

```bash
sudo dfu-util -l
```

Confirm the device still appears in DFU mode.

### Step 6 — Reconnect normally

Unplug and re-plug the USB cable **without** holding the Mute button.  
The device should boot with the new firmware and be detected as a normal USB audio device.
