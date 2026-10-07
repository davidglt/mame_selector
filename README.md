# MAME Selector

A Python desktop utility for browsing local MAME ROMs and managing a remote ROM directory over SSH.

## Project status

Initial repository setup. Application files, full license text, and dependencies will be added in a subsequent commit. Do not run the installation instructions until those files are present.

The application has not been tested against a live device.

## Features

- Local PNG thumbnails associated with ZIP filenames.
- Case-insensitive search and multiple selection across pages.
- Relative source paths resolved against the script directory; default: roms/.
- Batch SCP transfers using AsyncSSH.
- Password or private-key authentication.
- Optional legacy ssh-rsa compatibility.
- Editable connection settings saved in a .properties file.
- Remote ZIP listing through SFTP or explicit POSIX SSH commands.
- Marked remote ZIP deletion with full confirmation and per-file progress.
- Results distinguishing completed, failed, and pending operations.

## Installation

Once the application files are available, run from Windows CMD:

```cmd
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
mame_selector.cmd
```

Python with Tkinter is required. The launcher uses the local virtual environment when present.

## ROM layout

Place ROM ZIPs and corresponding PNGs in roms/ alongside the application directory. For example: roms/galaxian.zip and roms/galaxian.png. Only files directly inside the selected source directory are scanned.

## Security and limitations

Verify server fingerprints before trusting a new host. Changed host keys must be rejected. Passwords and key passphrases are not saved by default; optional credential saving stores them in plain text after confirmation. Never commit credentials, private keys, or local configuration.

Remote deletion is permanent. Confirm the exact server, directory, and filenames. No recursive deletion or wildcard deletion is intended. ROM dependencies are not detected: deleting a BIOS or parent ZIP can affect other games. A timeout or disconnect can leave an operation outcome uncertain; refresh the remote list before retrying.

The destination must exist and support SCP for copying. SSH-command listing and deletion require a POSIX shell; SFTP mode requires the SFTP subsystem. No ROMs or artwork are distributed.

## Author and license

Copyright (C) 2026 David González López-Tercero.

This project is free software under GNU GPL version 3 or, at your option, any later version, and is provided WITHOUT ANY WARRANTY.

SPDX-License-Identifier: GPL-3.0-or-later

The complete LICENSE file will be included with the application files.
