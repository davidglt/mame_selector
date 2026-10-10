"""Shared fixtures: isolated temporary BASE directory, no real configuration, network or dialogs."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tkinter as tk

import retro_selector as rs

PROFILE_DIRS = {'mame': 'roms_mame', 'samples': 'samples_mame', 'snes': 'roms_snes', 'megadrive': 'roms_md'}


class TempBaseCase(unittest.TestCase):
    """Redirects BASE, CONFIG and HOSTS to a temporary directory for each test."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        for name, value in (('BASE', self.base), ('CONFIG', self.base / 'retro_selector.properties'),
                            ('HOSTS', self.base / 'retro_selector_host_keys.json')):
            patcher = mock.patch.object(rs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def touch(self, directory, *names):
        folder = self.base / directory
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / name).write_bytes(b'test')
        return folder


class AppCase(TempBaseCase):
    """Builds the real Tk application on a hidden root; dialogs and threads are replaced by mocks."""

    def setUp(self):
        super().setUp()
        for directory in PROFILE_DIRS.values():
            (self.base / directory).mkdir()
        self.dialogs = {}
        for name, result in (('showerror', None), ('showwarning', None), ('askyesno', True)):
            patcher = mock.patch.object(rs.messagebox, name, mock.Mock(return_value=result))
            self.dialogs[name] = patcher.start()
            self.addCleanup(patcher.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f'No display available (use xvfb-run on Linux): {error}')
        self.root.withdraw()
        self.addCleanup(self.close_root)
        self.app = None

    def close_root(self):
        for job in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(job)
        self.root.destroy()

    def make_app(self, config=None):
        if config is not None:
            rs.CONFIG.write_text(config, encoding='utf-8')
        self.app = rs.App(self.root)
        return self.app

    def select(self, emulator, mode=None):
        if mode:
            self.app.v['content.mode'].set(mode)
        self.app.v['emulator.active'].set(emulator)

    def fill_connection(self, password='secret'):
        for key, value in (('ssh.host', 'ipad.invalid'), ('ssh.port', '2222'), ('ssh.username', 'mobile'),
                           ('ssh.password', password)):
            self.app.v[key].set(value)

    def local_names(self):
        return [path.name for path in self.app.roms]
