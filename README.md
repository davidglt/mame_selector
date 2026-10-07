# MAME Selector

Desktop MAME ROM and sample browser and remote ZIP manager built with Python, Tkinter, Pillow, and AsyncSSH.

Browse a local collection, select multiple ZIP files, transfer them over SCP, and list or delete selected remote ZIPs over SSH. Switch between ROMs and Samples in the same application: all functionality remains in `mame_selector.py`, with no second Python program.

## Project status

The ROMs/Samples update has not been runtime tested. The graphical interface and live device compatibility have not been verified. Test with expendable files before using remote deletion on your collection.

## Requirements

- Python with Tkinter.
- Dependencies listed in `requirements.txt`: Pillow and AsyncSSH.
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

Old `mame_selector.properties` files remain supported. Missing keys use defaults: `content.mode=roms`, `samples.source=samples/`, and `samples.remote_dir=/var/mobile/Media/ROMs/MAME4iOS/samples/`. Existing `rom.source` and `ssh.remote_dir` settings remain unchanged.

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

## Project files

| File | Purpose |
| --- | --- |
| `mame_selector.py` | Single application file, including ROMs/Samples mode switching and both panels. |
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
