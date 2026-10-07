# MAME Selector

Desktop MAME ROM and sample browser and remote ZIP manager built with Python, Tkinter, Pillow, and AsyncSSH.

Browse a local collection, select multiple ZIP files, transfer them over SCP, and list or delete selected remote ZIPs over SSH. Switch between ROMs and Samples in the same application: all functionality remains in `mame_selector.py`, with no second Python program.

## Project status

The ROMs/Samples update has not been runtime tested. The graphical interface and live device compatibility have not been verified. Test with expendable files before using remote deletion on your collection.

## Requirements

- Python with Tkinter.
- Dependencies listed in `requirements.txt`: Pillow, AsyncSSH and pyte (terminal emulation).
- A reachable SSH server and valid credentials.
- Existing local source and remote destination directories for the selected mode.
- SCP support for copying; SFTP or a compatible POSIX shell for listing and deletion.

The included launcher is intended for Windows CMD.

## Installation

Place the application files in your collection's parent directory. For the original setup:

```text
D:\MAME0.139RomCollectionByGhostware\
├── mame_selector.py
├── mame_selector.cmd
├── requirements.txt
├── README.md
├── LICENSE
├── mame_selector.properties.example
├── roms\
│   ├── galaxian.zip
│   ├── galaxian.png
│   ├── galaga.zip
│   └── galaga.png
└── samples\
    └── example.zip
```

From Windows CMD:

```cmd
cd /d D:\MAME0.139RomCollectionByGhostware
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
mame_selector.cmd
```

The launcher uses `.venv\Scripts\python.exe` when available, otherwise `python` from `PATH`. It does not require manual virtual-environment activation.

Alternatively, run directly:

```cmd
.venv\Scripts\python.exe mame_selector.py
```

## Quick start

1. Run `mame_selector.cmd`.
2. Choose `roms` or `samples` in `Content`.
3. Check the matching local source and click `Load` if you have edited its path.
4. Enter the SSH host, port, username, and credentials; check the matching remote destination.
5. Select the remote listing mode and enable legacy RSA only if required.
6. Click `Refresh` in the right panel.
7. Verify any new server fingerprint through a trusted channel before accepting it.
8. Mark local ZIPs and click `Copy selected`.
9. Review the content mode, destination, and complete batch list before confirming.
10. Click `Save` if you want to preserve the configuration, including the selected content mode.

For the first deletion test, use remote ZIP files which you can safely recreate.

## ROMs and Samples modes

The readonly `Content` selector determines which local collection and remote destination the panels and operations use. Both modes support search, pagination, multiple selection, copying, remote listing, and remote deletion.

The four paths are independently editable:

| UI field | Configuration key | Default |
| --- | --- | --- |
| `ROM source` | `rom.source` | `roms/` |
| `Samples source` | `samples.source` | `samples/` |
| `Remote ROMs` | `ssh.remote_dir` | `/var/mobile/Media/ROMs/MAME4iOS/roms/` |
| `Remote samples` | `samples.remote_dir` | `/var/mobile/Media/ROMs/MAME4iOS/samples/` |

The default sample folders are siblings of the ROM folders. Editing one path does not change the others. Use the separate `Browse...` buttons to change local paths. Browsing the active source loads it; browsing the inactive source only updates its setting.

### Switching content

Changing `Content` clears both local and remote marks, resets the search filters and local pagination, invalidates the previous remote list, and loads the newly selected local source. Panel titles identify the active content.

Click `Refresh` to load the new mode's remote list. A ROMs list cannot authorize deletion in Samples mode, or vice versa. The SSH endpoint and authentication settings are shared by both modes.

If the selected source does not exist, the application reports an error and leaves the local panel empty instead of showing files from the previous mode. Local and remote directories are not created automatically.

Mode and configuration controls are disabled during batch confirmation and remote operations. Each batch uses a captured selection and configuration, including the active source and destination. Copy and deletion confirmations show the content mode and destination.

### Existing configuration files

Old `mame_selector.properties` files remain supported. Missing keys use defaults: `content.mode=roms`, `samples.source=samples/`, and `samples.remote_dir=/var/mobile/Media/ROMs/MAME4iOS/samples/`. Existing `rom.source` and `ssh.remote_dir` settings remain unchanged. A file without `terminal.scrollback_lines` (older versions) uses the default `10000`; saving writes the key.

Clicking `Save` writes the new settings along with the existing ones. Internal operation snapshots are not written to the configuration file. You do not need to replace your local configuration with the example file.

## Local collections

Relative local sources are resolved against the directory containing `mame_selector.py`, not the current CMD working directory. Absolute source paths are also supported. Relative private-key paths use the same base directory.

Place optional PNG thumbnails beside their corresponding ZIP files, with the same filename stem:

```text
roms/
├── galaxian.zip
├── galaxian.png
├── galaga.zip
└── galaga.png
```

Only ZIP files directly inside the active source are scanned; subdirectories are not scanned. Missing or unreadable PNGs display `No image` in ROMs mode and a generic `Samples` placeholder in Samples mode. Sample ZIPs do not require PNGs. Images remain local and are not copied.

### Search and multiple selection

- Local search ignores case and matches the ZIP filename without its extension.
- An empty search includes all local ZIPs, displayed in pages of 40.
- Click a thumbnail or its graphical checkbox to mark or unmark a ZIP.
- Marks survive search changes and pagination within the same content mode.
- `Select all matches` includes matching ZIPs on every page.
- `Clear marks` clears the entire selection, including hidden marks.
- The counter reports marks outside the current filter.
- Loading a different source or changing content mode clears the previous selection.
- Editing the active source requires clicking `Load` before copying.

### Batch copying

`Copy selected` displays the content mode, complete file list, including marks hidden by the search filter, and the destination before transfer.

Files are copied sequentially over one authenticated SSH connection. Existing remote files with the same names may be overwritten. Successful files are unmarked; failed and pending files remain marked for retry.

Per-file errors allow the batch to continue while the connection remains usable. Connection loss or timeout stops the batch. The result window distinguishes completed, failed, and pending files.

Only selected ZIPs are copied. ROMs mode does not automatically copy samples; select Samples mode to manage those ZIPs separately. Parent ROMs, BIOS, sample dependencies, CHDs, and emulator compatibility are not checked or resolved.

## Remote listing

The right panel lists ZIP files present in the active mode's remote directory. File presence does not prove that the emulator can use the contents.

Click `Refresh` to load the list. Its search works independently of the local search and matches the remote filename. Changing the content mode, host, port, username, either configured remote directory, or listing mode invalidates the old list and clears remote marks.

Choose a listing mode explicitly:

| Mode | Requirements and behavior |
| --- | --- |
| `ssh` | Executes POSIX shell commands over SSH. Intended for Unix-like servers, including the original legacy device. Requires a POSIX shell and `printf` with NUL output support. |
| `sftp` | Uses the remote SFTP subsystem, which must be installed and enabled. |

There is no automatic fallback. Listing failures are reported rather than treated as an empty directory.

In `ssh` mode, filenames beginning with a dot are not listed. The SFTP listing does not have this shell-glob exclusion. Listing can include symbolic links to regular files, but deletion rejects symbolic links.

## Remote selection and deletion

Remote marks use textual checkbox indicators `[ ]` and `[x]` in the `Mark` column, rather than graphical checkbox widgets.

- Click the `Mark` column to toggle a file.
- Press Space to toggle a focused row.
- Clicking the filename alone does not mark the file.
- Marks survive remote search changes within a mode.
- `Select all matches` marks all matching remote filenames.
- `Clear marks` clears all remote marks, including hidden ones.

`Delete selected` displays the content mode, host, username, port, directory, and complete filename list before requesting confirmation. Hidden marks are included.

Deletion is permanent and does not modify local files. It targets exact ZIP paths without recursive deletion or wildcard deletion. Directories and symbolic links are rejected. BIOS, parent ROMs, and sample dependencies are not detected: removing required ZIPs can affect other games.

Successful deletions are unmarked. Failed or pending files remain marked if they still exist after refreshing. The result window reports individual outcomes, and the remote list refreshes after deletion or successful copying.

A timeout or disconnection can leave an individual outcome uncertain. Check the refreshed list before retrying. Concurrent server-side filesystem changes are not prevented; use a trusted remote directory.

## Progress bar

### Copying

The global bar gives equal weight to each file. Within the current file, it uses that file's transfer percentage. It is not the percentage of all bytes in the batch: a small ZIP and a large ZIP have the same global weight.

### Deletion

The bar advances after each file is processed, whether deletion succeeds or fails. It remains unchanged while waiting for the current operation's response.

A value of 100% means every file was processed, not that every file was deleted. Check the completed, failed, and pending counts. An interrupted batch retains the processed fraction instead of forcing 100%.

## Authentication and configuration

Set the SSH host, port, username, and absolute remote directory for each content mode. Choose `password` or `key` authentication. Connection settings are shared; sources and destinations are separate.

For key authentication, select the local private key, not its `.pub` file. Its corresponding public key must already be authorized on the server. Enter a passphrase if the private key is encrypted.

`Allow legacy SSH RSA (SHA-1)` permits `ssh-rsa` signatures. It does not enable every obsolete cipher or key-exchange algorithm. The initial defaults target the author's legacy device; change them for other servers and disable legacy compatibility when unnecessary.

Click `Save` to write `mame_selector.properties` next to the script. The file loads on startup; missing settings use defaults. Saving does not initiate a transfer.

The parser uses UTF-8 and literal `key=value` lines, splitting at the first equals sign. Windows backslashes do not require escaping. Relative local paths remain relative when saved. Lines beginning with `#` or `!` are comments.

Use `mame_selector.properties.example` as a credential-free template.

### Credential storage

Credentials are not saved by default. Optional saving stores passwords and key passphrases in plain text after confirmation. Anyone who can read the file can read them.

Clearing the option and clicking `Save` erases stored credentials without clearing the current interface values. Do not commit local configuration, private keys, or credentials. The provided `.gitignore` excludes local settings and common private-key filenames.

### Server identity

Verify a new server fingerprint through a trusted channel before accepting it. Approved public keys are stored in `mame_selector_host_keys.json` and pinned on the authenticated connection. Changed keys are rejected.

OpenSSH `known_hosts` is not imported automatically. Do not remove saved keys merely to bypass a warning; first verify whether the server was legitimately reinstalled or its identity changed.

## SSH terminal

Click `>_ SSH terminal` in the Configuration panel to open a separate interactive terminal window on the configured server. It uses the same AsyncSSH connection code as the file operations (no external `ssh` executable), so no second SSH-password prompt appears when valid credentials are already entered. The first connection to an unknown server still shows the explicit host-key trust prompt, and changed server keys are rejected. Remote prompts such as `sudo` or `su` are not suppressed or answered automatically.

- The host, port, user, authentication mode, password, key path, key passphrase, legacy-RSA setting and `Terminal scrollback lines` are copied when the window opens and stay fixed for that session. Changing the scrollback setting afterwards (it is locked while a session is open anyway) affects only the next session.
- Local ROM/sample folders and remote directories are not needed and are not used. No `cd` or any other command is run automatically.
- A real remote PTY is requested with `TERM=vt100`. Screen state is emulated with pyte and drawn in Tkinter: cursor addressing, erase operations, scrolling regions, bold/underline/reverse, basic colors, DEC line-drawing characters, application cursor keys, and device/cursor-position replies. Alternate-screen modes (`?47`, `?1047`, `?1049`) and bracketed paste (`?2004`) are also implemented. The remote PTY size follows the window size.
- Keys: printable characters (character at a time, no local echo), Enter, Backspace (sends DEL), Tab, Shift+Tab, Escape, arrows, Home/End/PageUp/PageDown/Insert/Delete, F1-F12, Alt+key (ESC prefix) and Ctrl+letter and other control characters. Ctrl+C, Ctrl+D, Ctrl+Z and Ctrl+V go to the remote side unchanged.
- Copy and paste: select text with the mouse and use the `Copy` button or Ctrl+Shift+C; paste with the `Paste` button or Ctrl+Shift+V. Pasting several lines asks for confirmation first, because the text may execute remote commands. Control characters (including Escape) are removed from pasted text. Bracketed paste is used only if the remote application enabled it. A redraw of a selected line clears the selection.
- `Disconnect` ends the session; after the session ends the button becomes `Close`. Closing the window also disconnects. The main window cannot be closed while a session is active.
- While a terminal session is active, file operations, `Save` and configuration edits are disabled (this initial implementation serializes them to avoid concurrent host-registry writes). When the session ends the remote listing is invalidated, because console commands may have changed remote files; click `Refresh` to reload it. Local selections are not modified.
- Scrollback: the terminal window has a vertical scrollbar and responds to the mouse wheel (3 lines per notch). Scrolling is purely local; no keys or escape sequences are sent to the remote side. The setting `Terminal scrollback lines` (`terminal.scrollback_lines` in `mame_selector.properties`, default `10000`) is the number of completed lines retained after they scroll off the top of the main screen; the visible rows are not counted and the remote PTY size never includes history or the scrollbar. The value must be a positive base-10 integer (`1`, `250`, `10000`); zero, negative, fractional, empty, malformed values, line breaks and NUL are rejected with an error before `Save` or terminal launch. There is no arbitrary upper limit other than the platform's maximum integer, but memory grows with the number of retained lines, so choose a value your computer can hold (a typical 80-column line needs on the order of a few hundred bytes).
- Following versus reading: at the bottom the view follows new output. After you scroll up, the lines you are reading stay in place while output arrives; when the oldest lines are discarded once the limit is exceeded, the view is clamped to the oldest retained line. Typing a key that is sent to the remote side, or pasting, returns to the live bottom; mouse-wheel, scrollbar, `Copy` and Ctrl+Shift+C do not. The cursor is hidden while browsing history. After the session ends the retained history can still be scrolled and read.
- Alternate-screen applications (`vi`, `vim`, `top`, `less`, using `?47`, `?1047` or `?1049`) are kept separate: their frames are never added to the history, the live screen is always shown, and the scrollbar and wheel are disabled (the wheel does nothing) until the application exits, when the previous screen and history are restored.
- Credentials are never put in process arguments, logs or extra settings files.

Scrollback limitations: only lines that scroll off the whole main screen are retained. Lines pushed out by an application's partial scrolling region (`TERM=vt100` full-screen programs that set a region smaller than the screen), screen redraws, cursor movement, erase and resize are not history, and a terminal cannot distinguish a program that redraws by scrolling the whole screen from ordinary shell output, so such output is retained like shell output. Lines removed by shrinking the window are not added to history, history lines are not reflowed when the window width changes, and `clear` sequences that erase the scrollback (`ESC[3J`) clear it. Selection and `Copy` apply to the rows currently displayed; text that was never displayed cannot be copied in one operation. Shrinking the window while an alternate-screen application runs may clip the restored main screen.

Not supported: mouse reporting, 256-color/truecolor terminal types, italics/blink, window-title changes, multiple concurrent terminals, SSH agent/X11/port forwarding, and non-UTF-8 remote locales. This is a VT100-level terminal, not a universal terminal emulator; applications that require a richer terminal type may render incorrectly.

### Smoke test

Use an expendable file and a test server first.

1. Open `>_ SSH terminal`; confirm the prompt appears without asking for the SSH password again.
2. Run `vi /tmp/mame_selector_test.txt`, press `i`, type text, press Escape, type `:wq` and Enter. Check the file with `cat`.
3. Run `top`; check that it refreshes, then press `q`.
4. Resize the window and run `stty size`; it should match the window.
5. Run `sleep 100` and press Ctrl+C.
6. Run `seq 1 300`, scroll up with the wheel and scrollbar, run `echo done` while scrolled (typing returns to the bottom), then open and quit `vi` and check the earlier output is still there.
7. Click `Disconnect`; confirm the main window re-enables its controls and `Refresh` is needed again.

Live vi/top behavior on the author's device has not been verified.

## Project files

| File | Purpose |
| --- | --- |
| `mame_selector.py` | Single application file, including ROMs/Samples mode switching, both panels and the SSH terminal. |
| `mame_selector.cmd` | Unchanged Windows launcher for `mame_selector.py`. |
| `requirements.txt` | Python dependencies. |
| `mame_selector.properties.example` | Credential-free configuration template for both modes. |
| `.gitignore` | Excludes local ROMs, samples, settings, and common key files. |
| `README.md` | Setup and usage documentation. |
| `LICENSE` | Complete GNU GPLv3 license text. |

Local files generated by the application:

- `mame_selector.properties`
- `mame_selector_host_keys.json`

The repository-root `/roms/` and `/samples/` folders are excluded from Git. Custom collection paths are not automatically added to `.gitignore`, and ignore rules do not remove files already tracked by Git.

## Troubleshooting

### Dependencies are missing

Install with the same interpreter used by the launcher:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If you do not use `.venv`, use `python -m pip install -r requirements.txt`.

When updating an existing installation, run the same command again to install the new `pyte` dependency (or `python -m pip install "pyte>=0.8.2"`).

### No local ZIPs appear

Check `Content` and its matching source field (`ROM source` or `Samples source`). The directory must exist and contain ZIP files directly inside it. Click `Load` after editing the active path. Switching modes intentionally clears previous files and marks.

### Remote operations require a valid local source

The current implementation uses shared configuration validation. `Refresh`, remote deletion, and `Save` also require the active local source directory to exist, even though they do not copy local files. Set an existing source directory for the selected mode before using them.

### Thumbnails are missing

Check that each optional PNG is readable, shares the ZIP filename stem, and is stored in the same directory. Sample ZIPs can be used without PNGs; their `Samples` placeholder is expected.

### The remote panel is empty after switching modes

Switching modes invalidates the previous list. Check `Remote ROMs` or `Remote samples` for the selected mode, then click `Refresh`. A missing or inaccessible remote directory produces an error; it is not created automatically.

### Authentication fails

Check the username, password, key file, passphrase, and server-side public-key authorization.

### SSH algorithm negotiation fails

Enable legacy RSA if the server requires `ssh-rsa`. Cipher or key-exchange errors require a separate compatibility adjustment; the checkbox does not enable those algorithms.

### Remote listing fails

Choose the mode supported by the server. `sftp` needs its subsystem; `ssh` needs a compatible POSIX shell. Also check that the active remote directory exists and is accessible.

### Copying or deletion fails

Check remote permissions and the result window. Copying requires SCP support. Deletion rejects symlinks and directories. Refresh the list before retrying uncertain outcomes.

## Limitations and assets

- Local and remote directories are not created automatically.
- Failed copies may leave partial remote files; there is no rollback.
- Each copy has a 10-minute timeout.
- Keep the application open until operations finish.
- ROM, BIOS, sample, and CHD dependencies and emulator compatibility are not resolved.
- No ROMs, samples, or artwork are distributed. Users are responsible for the appropriate rights.
- External assets and dependencies retain their respective licenses.

## Author and license

Copyright (C) 2026 David González López-Tercero.

GNU GPL version 3 or, at your option, any later version. WITHOUT ANY WARRANTY.

SPDX-License-Identifier: GPL-3.0-or-later

See [LICENSE](LICENSE) for the complete license text.
