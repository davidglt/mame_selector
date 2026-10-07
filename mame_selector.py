# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 David González López-Tercero
# GNU GPL version 3 or later. WITHOUT ANY WARRANTY. See LICENSE.
import asyncio
import json
import os
from pathlib import Path
import posixpath
import queue
import shlex
import stat
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import asyncssh
from PIL import Image, ImageDraw, ImageOps, ImageTk

BASE = Path(__file__).resolve().parent
CONFIG = BASE / 'mame_selector.properties'
HOSTS = BASE / 'mame_selector_host_keys.json'
DEFAULTS = {
    'content.mode': 'roms', 'rom.source': 'roms/', 'samples.source': 'samples/',
    'ssh.host': '192.168.69.53', 'ssh.port': '22', 'ssh.username': 'root',
    'ssh.remote_dir': '/var/mobile/Media/ROMs/MAME4iOS/roms/',
    'samples.remote_dir': '/var/mobile/Media/ROMs/MAME4iOS/samples/',
    'ssh.auth_mode': 'password', 'ssh.private_key': '', 'ssh.password': '',
    'ssh.key_passphrase': '', 'ssh.legacy_rsa': 'true',
    'ssh.save_credentials': 'false', 'ssh.remote_listing_mode': 'ssh',
}
PAGE_SIZE = 40


def local(value):
    path = Path(value.strip()).expanduser()
    return (path if path.is_absolute() else BASE / path).resolve()


def active_keys(mode):
    if mode == 'roms':
        return 'rom.source', 'ssh.remote_dir'
    if mode == 'samples':
        return 'samples.source', 'samples.remote_dir'
    raise ValueError('Select roms or samples.')


def atomic_write(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


class App:
    def __init__(self, root):
        self.root = root
        root.title('MAME Selector - ROMs / Samples - SSH / SCP')
        root.geometry('1450x950')
        root.minsize(1100, 760)
        values = DEFAULTS.copy()
        try:
            if CONFIG.exists():
                for line in CONFIG.read_text(encoding='utf-8-sig').splitlines():
                    if not line.strip() or line.lstrip().startswith(('#', '!')):
                        continue
                    key, separator, value = line.partition('=')
                    if separator and key.strip() in values:
                        values[key.strip()] = value
        except (OSError, UnicodeError) as error:
            messagebox.showwarning('Configuration', str(error))
        self.v = {key: tk.StringVar(value=value) for key, value in values.items()}
        if values['ssh.save_credentials'] != 'true':
            self.v['ssh.password'].set('')
            self.v['ssh.key_passphrase'].set('')
        for key, allowed in [('content.mode', ('roms', 'samples')),
                             ('ssh.auth_mode', ('password', 'key')),
                             ('ssh.remote_listing_mode', ('ssh', 'sftp'))]:
            if self.v[key].get() not in allowed:
                self.v[key].set(DEFAULTS[key])
        self.busy = False
        self.events = queue.Queue()
        self.settings, self.combos = [], []
        self.roms, self.filtered, self.remote = [], [], []
        self.marks, self.remote_marks = set(), set()
        self.loaded = self.remote_target = None
        self.page, self.job = 0, None
        self.images, self.cards, self.remote_rows = [], {}, {}
        self.search, self.remote_search = tk.StringVar(), tk.StringVar()
        self.count, self.remote_count = tk.StringVar(), tk.StringVar()
        self.status, self.pages = tk.StringVar(value='Ready'), tk.StringVar()
        self.build()
        for key in ('ssh.host', 'ssh.port', 'ssh.username', 'ssh.remote_dir',
                    'samples.remote_dir', 'ssh.remote_listing_mode'):
            self.v[key].trace_add('write', self.invalidate_remote)
        self.v['content.mode'].trace_add('write', self.mode_changed)
        self.search.trace_add('write', self.schedule_filter)
        self.remote_search.trace_add('write', lambda *args: self.render_remote())
        self.auth_state()
        self.update_titles()
        self.load()
        self.render_remote()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def source_key(self):
        return active_keys(self.v['content.mode'].get())[0]

    def update_titles(self):
        label = 'Samples' if self.v['content.mode'].get() == 'samples' else 'ROMs'
        self.local_panel.configure(text=f'Local {label}')
        self.remote_panel.configure(text=f'Remote {label}')

    def cancel_filter(self):
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None

    def mode_changed(self, *args):
        self.cancel_filter()
        self.marks.clear()
        self.roms, self.filtered = [], []
        self.loaded, self.page = None, 0
        self.search.set('')
        self.cancel_filter()
        self.remote_search.set('')
        self.invalidate_remote()
        self.update_titles()
        self.render()
        self.load()

    def build(self):
        menu = tk.Menu(self.root)
        menu.add_command(label='About / License', command=self.about)
        self.root.configure(menu=menu)
        config = ttk.LabelFrame(self.root, text='Configuration', padding=10)
        config.pack(fill='x', padx=10, pady=10)
        config.columnconfigure(1, weight=1)
        self.entries = {}
        labels = [('Content:', 'content.mode'), ('ROM source:', 'rom.source'),
                  ('Samples source:', 'samples.source'), ('SSH host / IP:', 'ssh.host'),
                  ('SSH port:', 'ssh.port'), ('User:', 'ssh.username'),
                  ('Remote ROMs:', 'ssh.remote_dir'), ('Remote samples:', 'samples.remote_dir'),
                  ('Authentication:', 'ssh.auth_mode'), ('Password:', 'ssh.password'),
                  ('Private key:', 'ssh.private_key'), ('Key passphrase:', 'ssh.key_passphrase'),
                  ('Remote listing:', 'ssh.remote_listing_mode')]
        choices = {'content.mode': ('roms', 'samples'), 'ssh.auth_mode': ('password', 'key'),
                   'ssh.remote_listing_mode': ('ssh', 'sftp')}
        for row, (label, key) in enumerate(labels):
            ttk.Label(config, text=label).grid(row=row, column=0, sticky='w', padx=8, pady=2)
            if key in choices:
                widget = ttk.Combobox(config, textvariable=self.v[key], values=choices[key], state='readonly')
                self.combos.append(widget)
                if key == 'ssh.auth_mode':
                    widget.bind('<<ComboboxSelected>>', lambda event: self.auth_state())
            else:
                widget = ttk.Entry(config, textvariable=self.v[key],
                                   show='*' if key in ('ssh.password', 'ssh.key_passphrase') else '')
                self.settings.append(widget)
            widget.grid(row=row, column=1, sticky='ew', pady=2)
            self.entries[key] = widget
            if key in ('rom.source', 'samples.source'):
                widget.bind('<Return>', lambda event: self.load())
                button = ttk.Button(config, text='Browse...', command=lambda k=key: self.browse_source(k))
                button.grid(row=row, column=2, padx=8)
                self.settings.append(button)
        for row, column, label, command in [(0, 3, 'Load', self.load),
                (10, 2, 'Browse...', self.browse_key), (14, 3, 'Save', self.save)]:
            button = ttk.Button(config, text=label, command=command)
            button.grid(row=row, column=column, padx=8)
            self.settings.append(button)
            if row == 10:
                self.key_browse = button
        for row, key, label in [(13, 'ssh.legacy_rsa', 'Allow legacy SSH RSA (SHA-1)'),
                (14, 'ssh.save_credentials', 'Save credentials in .properties (plain text)')]:
            check = ttk.Checkbutton(config, text=label, variable=self.v[key], onvalue='true', offvalue='false')
            check.grid(row=row, column=1, sticky='w')
            self.settings.append(check)
        ttk.Label(config, text='ssh: POSIX shell / sftp: SFTP subsystem').grid(row=12, column=2, columnspan=2)
        split = ttk.Panedwindow(self.root, orient='horizontal')
        split.pack(fill='both', expand=True, padx=10)
        left, right = ttk.LabelFrame(split), ttk.LabelFrame(split)
        self.local_panel, self.remote_panel = left, right
        split.add(left, weight=3)
        split.add(right, weight=2)
        for panel, variable in ((left, self.search), (right, self.remote_search)):
            tools = ttk.Frame(panel, padding=8)
            tools.pack(fill='x')
            ttk.Label(tools, text='Search:').pack(side='left')
            ttk.Entry(tools, textvariable=variable).pack(side='left', fill='x', expand=True, padx=5)
            ttk.Button(tools, text='Clear', command=lambda var=variable: var.set('')).pack(side='left')
            if panel is right:
                self.refresh_button = ttk.Button(tools, text='Refresh', command=self.refresh)
                self.refresh_button.pack(side='left', padx=5)
        for panel, remote in ((left, False), (right, True)):
            controls = ttk.Frame(panel, padding=8)
            controls.pack(fill='x')
            for text, command in [('Select all matches', lambda r=remote: self.select_all(r)),
                                  ('Clear marks', lambda r=remote: self.clear(r))]:
                button = ttk.Button(controls, text=text, command=command)
                button.pack(side='left', padx=3)
                self.settings.append(button)
        ttk.Label(left, textvariable=self.count, padding=8).pack(anchor='w')
        ttk.Label(right, textvariable=self.remote_count, padding=8).pack(anchor='w')
        area = ttk.Frame(left)
        area.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(area, highlightthickness=0)
        scroll = ttk.Scrollbar(area, command=self.canvas.yview)
        scroll.pack(side='right', fill='y')
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(fill='both', expand=True)
        self.grid = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=self.grid, anchor='nw')
        self.grid.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.canvas.bind('<MouseWheel>', self.wheel)
        footer = ttk.Frame(left, padding=8)
        footer.pack(fill='x')
        self.prev = ttk.Button(footer, text='Previous', command=lambda: self.turn(-1))
        self.prev.pack(side='left')
        ttk.Label(footer, textvariable=self.pages).pack(side='left', padx=8)
        self.next = ttk.Button(footer, text='Next', command=lambda: self.turn(1))
        self.next.pack(side='left')
        self.copy_button = ttk.Button(footer, command=self.copy)
        self.copy_button.pack(side='right')
        area = ttk.Frame(right, padding=8)
        area.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(area, columns=('marked', 'name'), show='headings')
        self.tree.heading('marked', text='Mark')
        self.tree.column('marked', width=55, stretch=False)
        self.tree.heading('name', text='Remote ZIP filename')
        self.tree.column('name', width=260)
        scroll = ttk.Scrollbar(area, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Button-1>', self.remote_click)
        self.tree.bind('<space>', self.remote_space)
        footer = ttk.Frame(right, padding=8)
        footer.pack(fill='x')
        self.delete_button = ttk.Button(footer, command=self.delete)
        self.delete_button.pack(side='right')
        self.progress = ttk.Progressbar(self.root, maximum=100)
        self.progress.pack(fill='x', padx=10, pady=5)
        ttk.Label(self.root, textvariable=self.status, padding=10).pack(anchor='w')

    def auth_state(self):
        password = self.v['ssh.auth_mode'].get() == 'password'
        self.entries['ssh.password'].configure(state='normal' if not self.busy and password else 'disabled')
        for widget in (self.entries['ssh.private_key'], self.entries['ssh.key_passphrase'], self.key_browse):
            widget.configure(state='normal' if not self.busy and not password else 'disabled')

    def set_busy(self, busy):
        self.busy = busy
        for widget in self.settings + [self.refresh_button]:
            widget.configure(state='disabled' if busy else 'normal')
        for widget in self.combos:
            widget.configure(state='disabled' if busy else 'readonly')
        self.auth_state()
        self.update_marks()

    def browse_source(self, key=None):
        if self.busy:
            return
        key = key or self.source_key()
        name = filedialog.askdirectory(initialdir=str(BASE))
        if name:
            try:
                value = Path(name).resolve().relative_to(BASE).as_posix()
            except ValueError:
                value = name
            self.v[key].set(value)
            if key == self.source_key():
                self.load()

    def browse_key(self):
        name = filedialog.askopenfilename(title='Select private key')
        if name:
            self.v['ssh.private_key'].set(name)

    def values(self):
        values = {key: var.get() for key, var in self.v.items()}
        for key in ('rom.source', 'samples.source', 'ssh.host', 'ssh.port', 'ssh.username',
                    'ssh.remote_dir', 'samples.remote_dir', 'ssh.private_key'):
            values[key] = values[key].strip()
        if any('\n' in value or '\r' in value or '\0' in value for value in values.values()):
            raise ValueError('Values cannot contain line breaks or NUL characters.')
        source_key, remote_key = active_keys(values['content.mode'])
        if not values[source_key] or not local(values[source_key]).is_dir():
            raise ValueError(f"Select an existing {values['content.mode']} source directory.")
        if not values['ssh.host'] or not values['ssh.username']:
            raise ValueError('Enter host and username.')
        port = int(values['ssh.port'])
        if not 1 <= port <= 65535:
            raise ValueError('Invalid SSH port.')
        values['ssh.port'] = str(port)
        if not values[remote_key].startswith('/'):
            raise ValueError('Use an absolute remote directory for the selected content.')
        if values['ssh.auth_mode'] not in ('password', 'key') or values['ssh.remote_listing_mode'] not in ('ssh', 'sftp'):
            raise ValueError('Invalid mode.')
        if values['ssh.auth_mode'] == 'key':
            path = local(values['ssh.private_key'])
            if not values['ssh.private_key'] or not path.is_file() or path.suffix.lower() == '.pub':
                raise ValueError('Select an existing private key, not a .pub file.')
        values['operation.source'] = values[source_key]
        values['operation.remote_dir'] = values[remote_key]
        return values

    def save(self):
        try:
            values = self.values()
            if values['ssh.save_credentials'] == 'true':
                if not messagebox.askyesno('Save credentials?', 'Save credentials in plain text?'):
                    return
            else:
                values['ssh.password'] = values['ssh.key_passphrase'] = ''
            atomic_write(CONFIG, '# UTF-8, literal values; paths relative to script\n' +
                         '\n'.join(f'{key}={values[key]}' for key in DEFAULTS) + '\n')
            self.status.set('Configuration saved.')
        except (OSError, ValueError) as error:
            messagebox.showerror('Save error', str(error))

    def load(self):
        if self.busy:
            return
        self.cancel_filter()
        try:
            text = self.v[self.source_key()].get().strip()
            directory = local(text)
            if not text or not directory.is_dir():
                raise ValueError(f'Source directory not found:\n{directory}')
            roms = sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == '.zip'),
                          key=lambda path: path.name.casefold())
        except (OSError, ValueError) as error:
            self.roms, self.filtered = [], []
            self.marks.clear()
            self.loaded = None
            self.page = 0
            self.render()
            messagebox.showerror('Source error', str(error))
            return
        if directory != self.loaded:
            self.marks.clear()
        self.loaded, self.roms = directory, roms
        self.marks.intersection_update(roms)
        self.filter()
        self.status.set(f"Loaded {len(roms)} local {self.v['content.mode'].get()} ZIPs.")

    def schedule_filter(self, *args):
        self.cancel_filter()
        self.job = self.root.after(200, self.filter)

    def filter(self):
        self.job = None
        query = self.search.get().strip().casefold()
        self.filtered = [path for path in self.roms if query in path.stem.casefold()]
        self.page = 0
        self.render()

    def wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), 'units')

    def render(self):
        for widget in self.grid.winfo_children():
            widget.destroy()
        self.cards.clear()
        self.images.clear()
        pages = max(1, (len(self.filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = max(0, min(self.page, pages - 1))
        self.pages.set(f'{self.page + 1} / {pages}')
        self.prev.configure(state='normal' if self.page else 'disabled')
        self.next.configure(state='normal' if self.page + 1 < pages else 'disabled')
        for column in range(4):
            self.grid.columnconfigure(column, weight=1)
        visible = self.filtered[self.page * PAGE_SIZE:(self.page + 1) * PAGE_SIZE]
        if not visible:
            ttk.Label(self.grid, text='No matching ZIPs.', padding=20).grid(row=0, column=0, columnspan=4)
        for index, path in enumerate(visible):
            try:
                with Image.open(path.with_suffix('.png')) as source:
                    image = ImageOps.exif_transpose(source).convert('RGBA')
                    image.thumbnail((150, 110), Image.Resampling.LANCZOS)
            except (OSError, ValueError):
                image = Image.new('RGBA', (150, 110), '#ddd')
                label = 'Samples' if self.v['content.mode'].get() == 'samples' else 'No image'
                ImageDraw.Draw(image).text((40, 45), label, fill='#555')
            background = Image.new('RGBA', (150, 110), '#eee')
            background.alpha_composite(image, ((150 - image.width) // 2, (110 - image.height) // 2))
            photo = ImageTk.PhotoImage(background.convert('RGB'))
            self.images.append(photo)
            card = tk.Frame(self.grid, bd=2, relief='solid')
            card.grid(row=index // 4, column=index % 4, padx=4, pady=4, sticky='nsew')
            variable = tk.BooleanVar(value=path in self.marks)
            check = tk.Checkbutton(card, text=path.stem, variable=variable, wraplength=145,
                                   command=lambda item=path: self.toggle(item))
            check.pack(fill='x')
            button = tk.Button(card, image=photo, relief='flat', command=lambda item=path: self.toggle(item))
            button.pack(fill='both', expand=True)
            for widget in (check, button):
                widget.bind('<MouseWheel>', self.wheel)
            self.cards[path] = card, variable, check, button
        self.update_marks()
        self.canvas.yview_moveto(0)

    def toggle(self, item, remote=False):
        if self.busy:
            return
        marks = self.remote_marks if remote else self.marks
        if item in marks:
            marks.remove(item)
        else:
            marks.add(item)
        self.render_remote() if remote else self.update_marks()

    def select_all(self, remote=False):
        if self.busy:
            return
        if remote:
            if self.remote_target is None:
                return
            query = self.remote_search.get().strip().casefold()
            self.remote_marks.update(name for name in self.remote if query in name.casefold())
            self.render_remote()
        else:
            query = self.search.get().strip().casefold()
            self.marks.update(path for path in self.roms if query in path.stem.casefold())
            self.update_marks()

    def clear(self, remote=False):
        if not self.busy:
            (self.remote_marks if remote else self.marks).clear()
            self.render_remote() if remote else self.update_marks()

    def update_marks(self):
        hidden = len(self.marks.difference(self.filtered))
        self.count.set(f'{len(self.filtered)} / {len(self.roms)} ZIPs | {len(self.marks)} selected ({hidden} outside filter)')
        self.copy_button.configure(text=f'Copy selected ({len(self.marks)})',
                                   state='normal' if self.marks and not self.busy else 'disabled')
        valid = self.remote_target is not None and self.remote_target == self.signature()
        self.delete_button.configure(text=f'Delete selected ({len(self.remote_marks)})',
                                     state='normal' if self.remote_marks and valid and not self.busy else 'disabled')
        for path, (card, variable, check, button) in self.cards.items():
            variable.set(path in self.marks)
            color = '#b9dcff' if path in self.marks else '#f0f0f0'
            card.configure(background=color)
            for widget in (check, button):
                widget.configure(background=color, state='disabled' if self.busy else 'normal')

    def turn(self, direction):
        self.page += direction
        self.render()

    def signature(self):
        mode = self.v['content.mode'].get()
        remote_key = active_keys(mode)[1]
        return (mode,) + tuple(self.v[key].get().strip() for key in
                     ('ssh.host', 'ssh.port', 'ssh.username', remote_key, 'ssh.remote_listing_mode'))

    def invalidate_remote(self, *args):
        self.remote, self.remote_target = [], None
        self.remote_marks.clear()
        self.render_remote()

    def render_remote(self):
        self.remote_marks.intersection_update(self.remote)
        self.tree.delete(*self.tree.get_children())
        self.remote_rows.clear()
        query = self.remote_search.get().strip().casefold()
        names = [name for name in self.remote if query in name.casefold()]
        for name in names:
            row = self.tree.insert('', 'end', values=('[x]' if name in self.remote_marks else '[ ]', name))
            self.remote_rows[row] = name
        hidden = len(self.remote_marks.difference(names))
        self.remote_count.set(f'{len(names)} / {len(self.remote)} ZIPs | {len(self.remote_marks)} marked ({hidden} outside filter)'
                              if self.remote_target else 'Not loaded — click Refresh')
        self.update_marks()

    def remote_click(self, event):
        if self.tree.identify_region(event.x, event.y) == 'cell' and self.tree.identify_column(event.x) == '#1':
            row = self.tree.identify_row(event.y)
            if row in self.remote_rows:
                self.toggle(self.remote_rows[row], True)
                return 'break'

    def remote_space(self, event):
        row = self.tree.focus()
        if row in self.remote_rows:
            self.toggle(self.remote_rows[row], True)
        return 'break'

    def refresh(self):
        if self.busy:
            return
        try:
            values = self.values()
        except (OSError, ValueError) as error:
            messagebox.showerror('Configuration', str(error))
            return
        self.set_busy(True)
        self.status.set('Loading remote list...')
        threading.Thread(target=self.list_worker, args=(values, self.signature()), daemon=True).start()

    def approve(self, endpoint, key):
        ready, answer = threading.Event(), {'yes': False}
        self.events.put(('host', endpoint, key.get_fingerprint(), answer, ready))
        ready.wait()
        return answer['yes']

    async def connect(self, values):
        host, port = values['ssh.host'], int(values['ssh.port'])
        endpoint = f'[{host}]:{port}'
        algorithms = '+ssh-rsa' if values['ssh.legacy_rsa'] == 'true' else '-ssh-rsa'
        key = await asyncio.wait_for(asyncssh.get_server_host_key(
            host, port=port, server_host_key_algs=algorithms, config=None), 30)
        if key is None:
            raise RuntimeError('No server host key.')
        registry = json.loads(HOSTS.read_text(encoding='utf-8')) if HOSTS.exists() else {}
        if not isinstance(registry, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in registry.items()):
            raise ValueError('Invalid host key registry.')
        public = key.export_public_key('openssh').decode('ascii').strip()
        if endpoint in registry:
            if registry[endpoint] != public:
                raise RuntimeError('Server key changed. Connection rejected. Verify the server before editing the registry.')
        else:
            if not await asyncio.to_thread(self.approve, endpoint, key):
                raise RuntimeError('Server identity rejected.')
            registry[endpoint] = public
            atomic_write(HOSTS, json.dumps(registry, indent=2) + '\n')
        options = dict(host=host, port=port, username=values['ssh.username'], known_hosts=([key], [], []),
                       server_host_key_algs=algorithms, signature_algs=algorithms,
                       agent_path=None, config=None, connect_timeout=15, login_timeout=30)
        if values['ssh.auth_mode'] == 'password':
            options.update(client_keys=[], password=values['ssh.password'], preferred_auth='password,keyboard-interactive')
        else:
            options.update(client_keys=[str(local(values['ssh.private_key']))],
                           passphrase=values['ssh.key_passphrase'] or None, preferred_auth='publickey')
        return await asyncssh.connect(**options)

    async def list_async(self, values):
        directory = values['operation.remote_dir']
        async with await self.connect(values) as connection:
            if values['ssh.remote_listing_mode'] == 'sftp':
                result = []
                async with connection.start_sftp_client() as sftp:
                    for name in await sftp.listdir(directory):
                        if not name.lower().endswith('.zip'):
                            continue
                        attrs = await sftp.stat(posixpath.join(directory, name))
                        if self.regular(attrs):
                            result.append(name)
            else:
                command = (f'directory={shlex.quote(directory)}; '
                    '[ -d "$directory" ] || { printf "%s\\n" "Directory not found" >&2; exit 1; }; '
                    '[ -r "$directory" ] && [ -x "$directory" ] || { printf "%s\\n" "Directory not accessible" >&2; exit 1; }; '
                    'for path in "$directory"/*; do [ -f "$path" ] || continue; '
                    'case "$path" in *.[zZ][iI][pP]) printf "%s\\000" "${path##*/}" ;; esac; done; exit 0')
                response = await connection.run(command, check=True, timeout=60)
                result = [name for name in response.stdout.split('\0') if name]
            return sorted(result, key=str.casefold)

    @staticmethod
    def regular(attrs):
        return ((attrs.permissions is not None and stat.S_ISREG(attrs.permissions))
                or (attrs.permissions is None and attrs.type == 1))

    def list_worker(self, values, target):
        try:
            names = asyncio.run(asyncio.wait_for(self.list_async(values), 180))
            self.events.put(('listed', names, target))
        except Exception as error:
            self.events.put(('list_error', f'{type(error).__name__}: {error}'))

    def report(self, title, text, action=None):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry('760x520')
        window.transient(self.root)
        area = ttk.Frame(window)
        area.pack(fill='both', expand=True)
        box = tk.Text(area, wrap='word')
        scroll = ttk.Scrollbar(area, command=box.yview)
        box.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        box.pack(fill='both', expand=True)
        box.insert('1.0', text)
        box.configure(state='disabled')
        footer = ttk.Frame(window, padding=10)
        footer.pack(fill='x')
        answer = {'yes': False}
        def accept():
            answer['yes'] = True
            window.destroy()
        ttk.Button(footer, text='Cancel' if action else 'Close', command=window.destroy).pack(side='right')
        if action:
            ttk.Button(footer, text=action, command=accept).pack(side='right', padx=8)
            window.grab_set()
            self.root.wait_window(window)
        return answer['yes']

    def copy(self):
        if self.busy or not self.marks:
            return
        try:
            values = self.values()
            if local(values['operation.source']) != self.loaded:
                raise ValueError('Source changed. Click Load first.')
            files = sorted(self.marks, key=lambda path: path.name.casefold())
            if any(not path.is_file() for path in files):
                raise ValueError('Selected files are missing. Reload the source.')
        except (OSError, ValueError) as error:
            messagebox.showerror('Configuration', str(error))
            return
        self.start_batch(files, values, False)

    def delete(self):
        if self.busy or not self.remote_marks:
            return
        try:
            values = self.values()
            if self.remote_target is None or self.remote_target != self.signature():
                raise ValueError('Remote target changed. Refresh first.')
            files = sorted(self.remote_marks, key=str.casefold)
            if not set(files).issubset(self.remote):
                raise ValueError('Stale remote selection. Refresh first.')
            for name in files:
                if (not name.lower().endswith('.zip') or '/' in name or '\\' in name
                        or any(ord(character) < 32 for character in name)):
                    raise ValueError(f'Unsafe filename: {name!r}')
        except (OSError, ValueError) as error:
            messagebox.showerror('Deletion configuration', str(error))
            return
        self.start_batch(files, values, True)

    def start_batch(self, files, values, deleting):
        action = 'Delete permanently' if deleting else 'Copy'
        warning = ('Permanent remote deletion. Local files are not modified.\n'
                   'BIOS and parent ZIPs may be required by other games.' if deleting
                   else 'Existing remote files may be overwritten.')
        text = (f"Content: {values['content.mode']}\n{action} {len(files)} files\n"
                f"Server: {values['ssh.username']}@{values['ssh.host']}\n"
                f"Port: {values['ssh.port']}\nDirectory: {values['operation.remote_dir']}\n\n{warning}\n"
                'Includes marks outside the current filter.\n\n' +
                '\n'.join(item if deleting else str(item) for item in files))
        self.set_busy(True)
        try:
            accepted = self.report('Confirm batch operation', text, action)
        except Exception:
            self.set_busy(False)
            raise
        if not accepted:
            self.set_busy(False)
            return
        self.progress['value'] = 0
        self.status.set('Connecting...')
        threading.Thread(target=self.batch_worker, args=(tuple(files), dict(values), deleting), daemon=True).start()

    async def batch_async(self, files, values, deleting, result):
        async with await self.connect(values) as connection:
            sftp = await connection.start_sftp_client() if deleting and values['ssh.remote_listing_mode'] == 'sftp' else None
            try:
                for index, item in enumerate(files, 1):
                    name = item if deleting else item.name
                    self.events.put(('status', f"{'Deleting' if deleting else 'Copying'} {index} / {len(files)}: {name}"))
                    last = [-1]
                    def progress(source, destination, copied, total):
                        percent = int(copied * 100 / total) if total else 100
                        if percent != last[0]:
                            last[0] = percent
                            self.events.put(('progress', index, len(files), name, percent, False))
                    try:
                        if deleting:
                            path = posixpath.join(values['operation.remote_dir'], name)
                            if sftp:
                                attrs = await asyncio.wait_for(sftp.lstat(path), 30)
                                if not self.regular(attrs):
                                    raise ValueError('Not a regular file; symlinks and directories are rejected.')
                                await asyncio.wait_for(sftp.remove(path), 30)
                            else:
                                quoted = shlex.quote(path)
                                command = (f'[ -f {quoted} ] && [ ! -L {quoted} ] '
                                    f'|| {{ printf "%s\\n" "Not a regular file or is a symlink" >&2; exit 1; }}; rm {quoted}')
                                await connection.run(command, check=True, timeout=30)
                        else:
                            await asyncio.wait_for(asyncssh.scp(item, (connection, values['operation.remote_dir'].rstrip('/') + '/'),
                                                               progress_handler=progress), 600)
                        result['completed'].append(item)
                        self.events.put(('completed', item, deleting))
                    except Exception as error:
                        result['failed'].append((item, f'{type(error).__name__}: {error}'))
                        if connection.is_closed() or isinstance(error, (asyncio.TimeoutError, asyncssh.ConnectionLost, asyncssh.DisconnectError)):
                            raise
                    finally:
                        self.events.put(('progress', index, len(files), name, 100, deleting))
            finally:
                if sftp:
                    sftp.exit()
                    await sftp.wait_closed()

    def batch_worker(self, files, values, deleting):
        result = {'completed': [], 'failed': [], 'fatal': '', 'deleting': deleting}
        try:
            asyncio.run(self.batch_async(files, values, deleting, result))
        except Exception as error:
            result['fatal'] = f'{type(error).__name__}: {error}'
        attempted = set(result['completed']) | {item for item, _ in result['failed']}
        result['pending'] = [item for item in files if item not in attempted]
        self.events.put(('done', result))

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == 'host':
                    _, endpoint, fingerprint, answer, ready = event
                    try:
                        answer['yes'] = messagebox.askyesno('Unknown SSH server',
                            f'{endpoint}\n\n{fingerprint}\n\nVerify through a trusted channel. Trust and save this key?')
                    finally:
                        ready.set()
                elif kind == 'status':
                    self.status.set(event[1])
                elif kind == 'progress':
                    _, index, count, name, percent, deleting = event
                    self.progress['value'] = ((index - 1) + percent / 100) * 100 / count
                    self.status.set(f"{'Processed' if deleting else 'Copying'} {index} / {count}: {name} — {self.progress['value']:.0f}% total")
                elif kind == 'completed':
                    _, item, deleting = event
                    (self.remote_marks if deleting else self.marks).discard(item)
                    if deleting:
                        self.remote = [name for name in self.remote if name != item]
                        self.render_remote()
                    self.update_marks()
                elif kind == 'listed':
                    if event[2] == self.signature():
                        self.remote, self.remote_target = event[1], event[2]
                        self.render_remote()
                    self.set_busy(False)
                    self.status.set('Remote list refreshed.')
                elif kind == 'list_error':
                    self.invalidate_remote()
                    self.set_busy(False)
                    self.status.set('Remote listing failed.')
                    messagebox.showerror('Remote listing', event[1])
                elif kind == 'done':
                    result = event[1]
                    marks = self.remote_marks if result['deleting'] else self.marks
                    marks.difference_update(result['completed'])
                    self.set_busy(False)
                    completed, failed, pending = len(result['completed']), len(result['failed']), len(result['pending'])
                    total = completed + failed + pending
                    self.progress['value'] = (completed + failed) * 100 / total if total else 0
                    summary = f'Completed: {completed} | Failed: {failed} | Pending: {pending}'
                    self.status.set(summary)
                    def label(item):
                        return item if isinstance(item, str) else item.name
                    lines = [summary, '', result['fatal'], '']
                    lines += ['COMPLETED: ' + label(item) for item in result['completed']]
                    lines += [f'FAILED: {label(item)} — {error}' for item, error in result['failed']]
                    lines += ['PENDING: ' + label(item) for item in result['pending']]
                    lines.append('\nTimeouts or disconnections can leave uncertain outcomes. Check the refreshed remote list.')
                    self.report('Batch results', '\n'.join(lines))
                    if result['deleting'] or result['completed']:
                        self.root.after(100, self.refresh)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def about(self):
        text = 'MAME Selector\nCopyright (C) 2026 David González López-Tercero\nGNU GPL version 3 or later. WITHOUT ANY WARRANTY.\n\n'
        try:
            text += (BASE / 'LICENSE').read_text(encoding='utf-8')
        except OSError:
            text += 'See LICENSE or https://www.gnu.org/licenses/gpl-3.0.html'
        self.report('About / License', text)

    def close(self):
        if self.busy:
            messagebox.showwarning('Operation in progress', 'Wait for the operation to finish.')
            return
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
