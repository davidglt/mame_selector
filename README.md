# MAME Selector

Desktop MAME ROM browser and remote ROM manager built with Python, Tkinter, Pillow, and AsyncSSH.

## Installation

From Windows CMD in the project directory:

```cmd
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
mame_selector.cmd
```

Python with Tkinter is required. The launcher uses the local .venv when available, otherwise python from PATH. Live device compatibility and the GUI have not been verified; syntax was checked.

## Local collection

The default source is roms/, resolved against the script directory. Absolute paths are also supported. Place matching PNGs beside ZIPs, for example roms/galaxian.zip and roms/galaxian.png. Only ZIP files directly inside the source are scanned. Missing or unreadable PNGs show a placeholder.

Search ignores case and matches ZIP filename stems. Click a thumbnail or checkbox to toggle a mark. Marks survive search and pagination. Select all matches includes every matching page; Clear marks clears the whole selection. Loading a different source clears marks.

Copy selected confirms the complete list, including hidden marks, then transfers ZIPs sequentially over one SSH connection. Successful files are unmarked. Failed and pending files remain marked. Connection loss or timeout stops the batch. Existing remote files may be overwritten; images and ROM dependencies are not copied.

## Remote listing and deletion

Refresh lists ZIPs in the configured remote directory. Search filters this list independently. Changing the target invalidates the list and remote marks.

Choose a listing mode explicitly:

- ssh: POSIX shell commands over SSH, intended for Unix-like servers including the original legacy device. Requires a POSIX shell and printf with NUL output support.
- sftp: requires an enabled SFTP subsystem.

There is no automatic fallback. Click the Mark column to toggle a remote file, or use Space on a focused row. Select all matches includes all filtered files; Clear marks removes all remote marks.

Delete selected requires confirmation of the host, user, port, directory, and full filename list. Deletion is permanent and does not affect local files. Exact ZIP paths are used without recursive or wildcard deletion. Directories and symlinks are rejected. The progress bar measures processed files, including failures, not only successful deletions. Results distinguish completed, failed, and pending files. The remote list refreshes after deletion or successful copying.

A timeout or disconnection may leave an individual operation outcome uncertain. Check the refreshed list before retrying. BIOS and parent ZIP dependencies are not detected; deleting them can affect other games. Concurrent server-side filesystem changes are not prevented.

## Authentication and settings

Set host, port, username, and an absolute remote directory. Authenticate using a password or private key with an optional passphrase. The corresponding public key must already be authorized on the server.

Allow legacy SSH RSA permits ssh-rsa signatures only; it does not enable every obsolete cipher or key exchange. Initial defaults target the author's legacy device and should be adjusted for other servers.

Save writes mame_selector.properties. UTF-8 key=value lines preserve literal values and split at the first equals sign. Relative source and private-key paths resolve against the script directory. Use mame_selector.properties.example as a credential-free template.

Credentials are not saved by default. Optional saving stores passwords and key passphrases in plain text after confirmation. Anyone with access to the file can read them. Clearing the option and saving erases stored credentials. Do not commit local configuration or keys.

Verify new host fingerprints through a trusted channel before acceptance. Approved public keys are stored in mame_selector_host_keys.json and pinned on authenticated connections. Changed keys are rejected. OpenSSH known_hosts is not imported automatically.

## Limitations

- The remote directory must exist and permit the requested operations.
- Copying requires SCP support.
- ROM set compatibility, parent ROMs, BIOS, samples, and CHDs are not resolved.
- Each copy has a 10-minute timeout; failed copies may leave partial files.
- Keep the application open until operations finish.
- No ROMs or artwork are distributed. Users are responsible for the appropriate rights.

## Author and license

Copyright (C) 2026 David González López-Tercero.

GNU GPL version 3 or, at your option, any later version. WITHOUT ANY WARRANTY.

SPDX-License-Identifier: GPL-3.0-or-later

See [LICENSE](LICENSE) for the complete license text. External assets and dependencies retain their respective licenses.
