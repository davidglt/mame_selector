# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 David González López-Tercero
# GNU GPL version 3 or later. WITHOUT ANY WARRANTY. See LICENSE.
import asyncio
import codecs
import collections
import inspect
import json
import math
import os
from pathlib import Path
import posixpath
import queue
import re
import shlex
import stat
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont
import asyncssh
from PIL import Image, ImageDraw, ImageOps, ImageTk
import pyte

BASE = Path(__file__).resolve().parent
CONFIG = BASE / 'retro_selector.properties'
HOSTS = BASE / 'retro_selector_host_keys.json'
DEFAULTS = {
    'emulator.active': 'mame', 'content.mode': 'roms', 'rom.source': 'roms_mame/',
    'samples.source': 'samples_mame/', 'snes.rom.source': 'roms_snes/',
    'megadrive.rom.source': 'roms_md/',
    'ssh.host': '192.168.69.53', 'ssh.port': '22', 'ssh.username': 'root',
    'ssh.remote_dir': '/var/mobile/Media/ROMs/MAME4iOS/roms/',
    'samples.remote_dir': '/var/mobile/Media/ROMs/MAME4iOS/samples/',
    'snes.remote_dir': '/var/mobile/Media/ROMs/Snes9xEX/roms/',
    'megadrive.remote_dir': '/var/mobile/Media/ROMs/MD.emu/roms/',
    'ssh.auth_mode': 'password', 'ssh.private_key': '', 'ssh.password': '',
    'ssh.key_passphrase': '', 'ssh.legacy_rsa': 'true',
    'ssh.save_credentials': 'false', 'ssh.remote_listing_mode': 'ssh',
    'terminal.scrollback_lines': '10000',
}
CONNECTION_KEYS = ('ssh.host', 'ssh.port', 'ssh.username', 'ssh.auth_mode', 'ssh.password',
                   'ssh.private_key', 'ssh.key_passphrase', 'ssh.legacy_rsa')
SCROLLBACK_KEY = 'terminal.scrollback_lines'
EMULATORS = ('mame', 'snes', 'megadrive')
EMULATOR_NAMES = {'mame': 'MAME', 'snes': 'SNES', 'megadrive': 'Sega Mega Drive / Genesis'}
LEGACY_ROM_SOURCE = 'roms/'  # rom.source default used before profiles existed
SNES_EXTENSIONS = ('.sfc', '.smc', '.swc', '.fig', '.zip')
MEGADRIVE_EXTENSIONS = ('.bin', '.md', '.gen', '.smd', '.zip')
ENUM_KEYS = {'emulator.active': EMULATORS, 'content.mode': ('roms', 'samples'),
             'ssh.auth_mode': ('password', 'key'), 'ssh.remote_listing_mode': ('ssh', 'sftp')}
MAX_SCROLLBACK = sys.maxsize  # collections.deque(maxlen=...) cannot represent more; no lower policy cap
PAGE_SIZE = 40


def local(value):
    path = Path(value.strip()).expanduser()
    return (path if path.is_absolute() else BASE / path).resolve()


def parse_scrollback(text):
    """Return the retained history line count from a positive base-10 integer string."""
    message = ('Terminal scrollback lines must be a positive whole number '
               f'(1 to {MAX_SCROLLBACK}), for example 10000.')
    if not isinstance(text, str) or any(c in text for c in '\r\n\0'):
        raise ValueError('Terminal scrollback lines cannot contain line breaks or NUL characters.')
    text = text.strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 40:
        raise ValueError(message)
    number = int(text)
    if not 1 <= number <= MAX_SCROLLBACK:
        raise ValueError(message)
    return number


def parse_properties(text):
    """Return the known settings found in properties text; unknown keys and comments are ignored."""
    found = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(('#', '!')):
            continue
        key, separator, value = line.partition('=')
        if separator and key.strip() in DEFAULTS:
            found[key.strip()] = value
    return found


def resolve_config(found):
    """Merge found settings over defaults. Legacy keys (rom.source, ssh.remote_dir, samples.*)
    stay MAME settings; missing SNES/emulator keys take their defaults."""
    values = DEFAULTS.copy()
    values.update(found)
    if found and 'rom.source' not in found and not any(
            key == 'emulator.active' or key.startswith(('snes.', 'megadrive.')) for key in found):
        values['rom.source'] = LEGACY_ROM_SOURCE
    for key, allowed in ENUM_KEYS.items():
        if values[key] not in allowed:
            values[key] = DEFAULTS[key]
    return values


def active_keys(mode, emulator='mame'):
    """Return the (local source key, remote directory key) of a profile."""
    if emulator == 'snes':
        return 'snes.rom.source', 'snes.remote_dir'
    if emulator == 'megadrive':
        return 'megadrive.rom.source', 'megadrive.remote_dir'
    if emulator != 'mame':
        raise ValueError('Select MAME, SNES or Sega Mega Drive / Genesis.')
    if mode == 'roms':
        return 'rom.source', 'ssh.remote_dir'
    if mode == 'samples':
        return 'samples.source', 'samples.remote_dir'
    raise ValueError('Select roms or samples.')


def profile_extensions(emulator):
    """Lowercase file extensions handled by a profile."""
    if emulator == 'snes':
        return SNES_EXTENSIONS
    return MEGADRIVE_EXTENSIONS if emulator == 'megadrive' else ('.zip',)


def shell_patterns(extensions):
    """Case-insensitive shell glob alternatives for fixed, trusted extensions."""
    return '|'.join('*' + ''.join(f'[{c.lower()}{c.upper()}]' if c.isalpha() else c for c in ext)
                    for ext in extensions)


def sample_placeholder():
    scale = 4
    image = Image.new('RGBA', (150 * scale, 110 * scale), '#ddd')
    draw = ImageDraw.Draw(image)
    color = '#555'
    draw.rectangle(tuple(v * scale for v in (76, 22, 81, 81)), fill=color)
    head = Image.new('RGBA', (32 * scale, 18 * scale), (0, 0, 0, 0))
    ImageDraw.Draw(head).ellipse((0, 0, head.width - 1, head.height - 1), fill=color)
    head = head.rotate(25, resample=Image.Resampling.BICUBIC, expand=True)
    image.alpha_composite(head, (49 * scale, 65 * scale))
    def curve(points):
        result = []
        for index in range(33):
            t = index / 32
            weights = ((1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3)
            result.append(tuple(sum(w*p[axis] for w, p in zip(weights, points)) * scale for axis in (0, 1)))
        return result
    flag = curve(((81, 22), (81, 37), (113, 35), (96, 63)))
    flag += curve(((96, 63), (100, 44), (82, 48), (81, 34)))
    draw.polygon(flag, fill=color)
    return image.resize((150, 110), Image.Resampling.LANCZOS)


SVG_COLORS = {'dark': '#383842', 'light': '#dddde5', 'mid': '#626273', 'blue': '#4386cf',
              'red': '#d85660', 'green': '#50a878', 'yellow': '#edc54e'}
PLACEHOLDER_SCALE = 4
_placeholders = {}


def svg_points(data):
    """Flatten an SVG path (M/L/H/V/C/Z, absolute or relative) into a list of (x, y) points."""
    tokens = re.findall(r'[A-Za-z]|-?\d*\.?\d+', data)
    points, index, command = [], 0, ''
    x = y = start_x = start_y = 0.0
    while index < len(tokens):
        if tokens[index].isalpha():
            command, index = tokens[index], index + 1
            if command in 'Zz':
                x, y = start_x, start_y
                continue
        relative = command.islower()
        kind = command.upper()
        count = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'C': 6}[kind]
        args = [float(t) for t in tokens[index:index + count]]
        index += count
        if kind in 'ML':
            nx, ny = (x + args[0], y + args[1]) if relative else (args[0], args[1])
        elif kind == 'H':
            nx, ny = (x + args[0] if relative else args[0]), y
        elif kind == 'V':
            nx, ny = x, (y + args[0] if relative else args[0])
        else:
            pts = [(x, y)] + [(x + a, y + b) if relative else (a, b) for a, b in zip(args[::2], args[1::2])]
            for step in range(1, 17):
                t = step / 16
                weights = ((1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3)
                points.append(tuple(sum(w * p[axis] for w, p in zip(weights, pts)) for axis in (0, 1)))
            nx, ny = pts[3]
        x, y = nx, ny
        if kind == 'M':
            start_x, start_y = x, y
            command = 'l' if relative else 'L'  # further pairs are implicit line-tos
        if kind != 'C':
            points.append((x, y))
    return points


def render_placeholder(shapes):
    """Draw transparent 128x128 SVG-equivalent shapes: ('path'|'ellipse'|'line'|'pill', ...)."""
    k = PLACEHOLDER_SCALE
    image = Image.new('RGBA', (128 * k, 128 * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    def scaled(points):
        return [(px * k, py * k) for px, py in points]
    def outline(points, width, closed=True):
        if width:
            points = scaled(points + points[:1] if closed else points)
            draw.line(points, fill=SVG_COLORS['dark'], width=round(width * k), joint='curve')
            for px, py in points if closed else (points[0], points[-1]):
                radius = width * k / 2
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=SVG_COLORS['dark'])
    for shape in shapes:
        kind, fill, width = shape[0], shape[1], shape[2]
        if kind == 'path':
            points = svg_points(shape[3])
            draw.polygon(scaled(points), fill=SVG_COLORS[fill])
            outline(points, width)
        elif kind == 'ellipse':
            cx, cy, rx, ry = shape[3:]
            draw.ellipse(((cx - rx) * k, (cy - ry) * k, (cx + rx) * k, (cy + ry) * k), fill=SVG_COLORS[fill])
            if width:
                draw.ellipse(((cx - rx) * k, (cy - ry) * k, (cx + rx) * k, (cy + ry) * k),
                             outline=SVG_COLORS['dark'], width=round(width * k))
        elif kind == 'line':  # round-capped stroke
            outline(svg_points(shape[3]), width, False)
        elif kind == 'pill':  # rect with fully rounded ends, rotated about a point
            x, y, w, h, angle, cx, cy = shape[3:]
            cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            ends = [(x + h / 2, y + h / 2), (x + w - h / 2, y + h / 2)]
            ends = [(cx + (px - cx) * cos - (py - cy) * sin, cy + (px - cx) * sin + (py - cy) * cos)
                    for px, py in ends]
            ends = scaled(ends)
            draw.line(ends, fill=SVG_COLORS[fill], width=round(h * k))
            for px, py in ends:
                radius = h * k / 2
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=SVG_COLORS[fill])
    return image.resize((128, 128), Image.Resampling.LANCZOS)


# Shapes equal to assets/snes-sin-caratula.svg and assets/mame-sin-caratula.svg
PLACEHOLDER_SHAPES = {
    'snes': [
        ('path', 'light', 5, 'M42 40h44c20 0 33 17 29 36-3 14-14 22-25 17L75 83H53L38 93C27 98 16 90 13 76 9 57 22 40 42 40Z'),
        ('path', 'dark', 0, 'M30 53h12v10h10v12H42v10H30V75H20V63h10Z'),
        ('pill', 'mid', 0, 53, 69, 13, 5, -25, 59, 71),
        ('pill', 'mid', 0, 67, 69, 13, 5, -25, 73, 71),
        ('ellipse', 'blue', 2, 96, 53, 6, 6), ('ellipse', 'red', 2, 107, 64, 6, 6),
        ('ellipse', 'green', 2, 85, 64, 6, 6), ('ellipse', 'yellow', 2, 96, 75, 6, 6)],
    'mame': [
        ('path', 'light', 5, 'm23 67 82 0 12 27H11Z'),
        ('path', 'mid', 5, 'M11 94h106v14H11Z'),
        ('ellipse', 'mid', 0, 40, 78, 15, 5),
        ('line', 'dark', 7, 'M40 76V45'),
        ('ellipse', 'red', 5, 40, 34, 13, 13),
        ('ellipse', 'blue', 2, 77, 75, 7, 5), ('ellipse', 'yellow', 2, 96, 75, 7, 5),
        ('ellipse', 'green', 2, 84, 86, 7, 5)],
    'megadrive': [
        ('path', 'light', 5, 'M24 20h80l8 12v78H16V32Z'),
        ('path', 'dark', 0, 'M32 34h64v34H32Z'),
        ('path', 'mid', 0, 'M30 80h68v8H30Z'),
        ('path', 'mid', 0, 'M30 94h68v8H30Z'),
        ('ellipse', 'red', 2, 64, 51, 12, 8)],
}


def emulator_placeholder(emulator):
    """Transparent 'no cover' icon for a profile, rendered once and cached."""
    if emulator not in _placeholders:
        _placeholders[emulator] = render_placeholder(PLACEHOLDER_SHAPES[emulator])
    return _placeholders[emulator].copy()


SPACE_NOT_LOADED = 'Disk space: not loaded'
SPACE_LOADING = 'Disk space: loading...'
DF_LINE = re.compile(r'(\d+)\s+(\d+)\s+(\d+)\s+\d+%\s+/')


def format_size(size):
    value = float(size)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024:
            return f'{int(value)} B' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024
    return f'{value:.1f} PiB'


def format_space(space):
    """space is (available, total) in bytes, or None when it could not be determined."""
    if space is None:
        return 'Disk space: unavailable'
    available, total = space
    return f'Disk space: {format_size(available)} available of {format_size(total)} ({available * 100 / total:.0f}% free)'


def vfs_space(attrs):
    unit = attrs.frsize or attrs.bsize
    if not unit or not attrs.blocks or attrs.bavail > attrs.blocks:
        return None
    return attrs.bavail * unit, attrs.blocks * unit


def parse_df(text):
    """Parse `df -Pk` output (1024-byte blocks); returns (available, total) in bytes or None."""
    for line in reversed(text.splitlines()):
        match = DF_LINE.search(line)
        if match:
            total, _, available = (int(group) * 1024 for group in match.groups())
            if total and available <= total:
                return available, total
    return None


def atomic_write(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


TERM_TYPE = 'vt100'
DECCKM = 1 << 5
ALT_SCREEN_MODES = (47, 1047, 1049)
BRACKETED_PASTE_MODE = 2004
DECCOLM_MODE = 3
OUTPUT_LIMIT = 1 << 20
PASTE_START, PASTE_END = '\x1b[200~', '\x1b[201~'
SHIFT_MASK, CONTROL_MASK = 0x1, 0x4
ALT_MASK = 0x20000 if sys.platform == 'win32' else 0x8
ARROWS = {'Up': 'A', 'Down': 'B', 'Right': 'C', 'Left': 'D',
          'KP_Up': 'A', 'KP_Down': 'B', 'KP_Right': 'C', 'KP_Left': 'D'}
KEYS = {'Return': '\r', 'KP_Enter': '\r', 'BackSpace': '\x7f', 'Tab': '\t', 'Escape': '\x1b',
        'ISO_Left_Tab': '\x1b[Z', 'Delete': '\x1b[3~', 'KP_Delete': '\x1b[3~',
        'Insert': '\x1b[2~', 'KP_Insert': '\x1b[2~', 'Home': '\x1b[1~', 'KP_Home': '\x1b[1~',
        'End': '\x1b[4~', 'KP_End': '\x1b[4~', 'Prior': '\x1b[5~', 'KP_Prior': '\x1b[5~',
        'Next': '\x1b[6~', 'KP_Next': '\x1b[6~', 'F1': '\x1bOP', 'F2': '\x1bOQ', 'F3': '\x1bOR',
        'F4': '\x1bOS', 'F5': '\x1b[15~', 'F6': '\x1b[17~', 'F7': '\x1b[18~', 'F8': '\x1b[19~',
        'F9': '\x1b[20~', 'F10': '\x1b[21~', 'F11': '\x1b[23~', 'F12': '\x1b[24~'}
CONTROL_KEYS = {'space': 0, 'at': 0, 'bracketleft': 0x1b, 'backslash': 0x1c, 'bracketright': 0x1d,
                'asciicircum': 0x1e, 'underscore': 0x1f, 'slash': 0x1f, 'question': 0x7f}
ANSI_COLORS = {'black': '#000000', 'red': '#cd3131', 'green': '#0dbc79', 'brown': '#e5e510',
               'blue': '#2472c8', 'magenta': '#bc3fbc', 'cyan': '#11a8cd', 'white': '#e5e5e5',
               'brightblack': '#666666', 'brightred': '#f14c4c', 'brightgreen': '#23d18b',
               'brightbrown': '#f5f543', 'brightblue': '#3b8eea', 'brightmagenta': '#d670d6',
               'brightcyan': '#29b8db', 'brightwhite': '#ffffff'}
TERMINAL_FG, TERMINAL_BG = '#e5e5e5', '#000000'


def translate_key(keysym, char, state, application_cursor=False):
    """Return the text a key press sends to the remote PTY, or None to send nothing."""
    ctrl, alt, shift = state & CONTROL_MASK, state & ALT_MASK, state & SHIFT_MASK
    printable = bool(char) and len(char) == 1 and char >= ' ' and char != '\x7f'
    if ctrl and alt and printable:
        ctrl = alt = 0  # AltGr is reported as Ctrl+Alt on Windows
    if keysym in ARROWS:
        return ('\x1bO' if application_cursor else '\x1b[') + ARROWS[keysym]
    if keysym == 'Tab' and shift:
        text = '\x1b[Z'
    elif keysym == 'BackSpace' and ctrl:
        text = '\x08'
    elif keysym in KEYS:
        text = KEYS[keysym]
    elif ctrl:
        key = keysym if len(keysym) == 1 else (char if printable else '')
        if len(key) == 1 and key.isascii() and key.isalpha():
            text = chr(ord(key.lower()) - 96)
        elif keysym in CONTROL_KEYS:
            text = chr(CONTROL_KEYS[keysym])
        elif len(char) == 1 and char < ' ':
            text = char
        else:
            return None
    elif printable:
        text = char
    else:
        return None
    return '\x1b' + text if alt and not text.startswith(('\x1b[', '\x1bO')) else text


def paste_payload(text, bracketed=False):
    """Return (data, multiline) for pasting text; control characters are removed."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = ''.join(c for c in text if c in '\t\n' or not (c < ' ' or '\x7f' <= c <= '\x9f'))
    multiline = '\n' in text
    text = text.replace('\n', '\r')
    return (PASTE_START + text + PASTE_END if bracketed else text), multiline


class TerminalScreen(pyte.Screen):
    """pyte screen adding alternate screens, bracketed paste, safe handling of private CSI
    and bounded scrollback of lines that scroll off the main screen."""
    alt = None
    bracketed_paste = False
    reply = None

    def __init__(self, columns, lines, scrollback=10000):
        self.history = collections.deque(maxlen=scrollback)
        self.history_total = 0  # lines ever retained, including evicted ones
        self.styles = {}
        super().__init__(columns, lines)
        for name in set(pyte.Stream.csi.values()) - {'set_mode', 'reset_mode'}:
            method = getattr(self, name)
            parameters = inspect.signature(method).parameters
            if 'private' not in parameters and not any(p.kind is p.VAR_KEYWORD for p in parameters.values()):
                setattr(self, name, self.ignoring_private(method))

    @staticmethod
    def ignoring_private(method):
        def call(*args, private=False, **kwargs):
            if not private:
                return method(*args, **kwargs)
        return call

    @property
    def application_cursor(self):
        return DECCKM in self.mode

    def reset(self):
        self.alt, self.bracketed_paste = None, False
        super().reset()

    def history_line(self, line):
        """Compact (text, style) runs of a screen row, without trailing default blanks."""
        cells = [line[x] for x in range(min(self.columns, max(line, default=-1) + 1))]
        while cells and cells[-1] == self.default_char:
            cells.pop()
        runs = []
        for char in cells:
            if not char.data:
                continue
            style = self.styles.get(char[1:])
            if style is None:
                if len(self.styles) >= 1024:
                    self.styles.clear()
                style = self.styles[char[1:]] = char._replace(data='')
            if runs and runs[-1][1] is style:
                runs[-1][0].append(char.data)
            else:
                runs.append(([char.data], style))
        return tuple((''.join(data), style) for data, style in runs)

    def index(self):
        # Only a real scroll of the whole main screen creates history; application
        # scrolling regions and the alternate screen never do.
        if self.alt is None and self.history.maxlen:
            top, bottom = self.margins or (0, self.lines - 1)
            if self.cursor.y == bottom and top == 0 and bottom == self.lines - 1:
                self.history.append(self.history_line(self.buffer[0]))
                self.history_total += 1
        super().index()

    def erase_in_display(self, how=0, *args, **kwargs):
        super().erase_in_display(how, *args, **kwargs)
        if how == 3 and self.alt is None:
            self.history.clear()

    def write_process_input(self, data):
        if self.reply:
            self.reply(data)

    def set_mode(self, *modes, **kwargs):
        if kwargs.get('private'):
            remaining = []
            for mode in modes:
                if mode in ALT_SCREEN_MODES:
                    self.enter_alternate()
                elif mode == BRACKETED_PASTE_MODE:
                    self.bracketed_paste = True
                elif mode != DECCOLM_MODE:
                    remaining.append(mode)
            modes = remaining
        if modes:
            super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs):
        if kwargs.get('private'):
            remaining = []
            for mode in modes:
                if mode in ALT_SCREEN_MODES:
                    self.exit_alternate()
                elif mode == BRACKETED_PASTE_MODE:
                    self.bracketed_paste = False
                elif mode != DECCOLM_MODE:
                    remaining.append(mode)
            modes = remaining
        if modes:
            super().reset_mode(*modes, **kwargs)

    def enter_alternate(self):
        if self.alt is not None:
            return
        self.alt = {'buffer': {y: dict(line) for y, line in self.buffer.items()},
                    'x': self.cursor.x, 'y': self.cursor.y, 'attrs': self.cursor.attrs,
                    'margins': self.margins}
        self.buffer.clear()
        self.margins = None
        self.dirty.update(range(self.lines))

    def exit_alternate(self):
        saved, self.alt = self.alt, None
        if saved is None:
            return
        self.buffer.clear()
        for y, cells in saved['buffer'].items():
            if y < self.lines:
                self.buffer[y].update({x: cell for x, cell in cells.items() if x < self.columns})
        margins = saved['margins']
        self.margins = margins if margins is not None and margins.bottom < self.lines else None
        self.cursor.x, self.cursor.y, self.cursor.attrs = saved['x'], saved['y'], saved['attrs']
        self.ensure_hbounds()
        self.ensure_vbounds()
        self.dirty.update(range(self.lines))

    def resize(self, lines=None, columns=None):
        previous = self.columns
        super().resize(lines, columns)
        self.tabstops = {x for x in self.tabstops if x < self.columns}
        self.tabstops.update(range(max(8, (previous + 7) // 8 * 8), self.columns, 8))
        self.ensure_hbounds()
        self.ensure_vbounds()


class TerminalLink:
    """Thread-safe exchange between the Tk main thread and the asyncio worker thread."""
    def __init__(self, size):
        self.size = size
        self.out = queue.Queue()
        self.lock = threading.Lock()
        self.pending = 0
        self.loop = self.task = self.inbox = None
        self.closing = False

    def attach(self, loop, task, inbox):
        with self.lock:
            self.loop, self.task, self.inbox = loop, task, inbox
            if self.closing:
                loop.call_soon(task.cancel)

    def send(self, item):
        with self.lock:
            loop, inbox, closing = self.loop, self.inbox, self.closing
        if loop is None or closing:
            return False
        try:
            loop.call_soon_threadsafe(inbox.put_nowait, item)
        except RuntimeError:
            return False
        return True

    def close(self):
        with self.lock:
            if self.closing:
                return
            self.closing = True
            loop, task = self.loop, self.task
        if loop is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def put_data(self, data):
        with self.lock:
            self.pending += len(data)
        self.out.put(('data', data))

    def drain(self, limit=262144):
        events, total = [], 0
        while total < limit:
            try:
                event = self.out.get_nowait()
            except queue.Empty:
                break
            events.append(event)
            if event[0] == 'data':
                total += len(event[1])
                with self.lock:
                    self.pending -= len(event[1])
        return events


class TerminalWindow:
    """Tkinter renderer for a pyte screen; all methods run on the Tk main thread."""
    def __init__(self, app, values):
        self.app, self.state, self.destroy_on_end = app, 'connecting', False
        self.pump_job = self.resize_job = self.render_job = None
        self.offset, self.seen_total = 0, 0  # lines scrolled up from the live bottom
        self.history_view, self.rendered_top, self.bar_state = False, None, None
        self.scrollback = parse_scrollback(values[SCROLLBACK_KEY])  # fixed for this session
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.window = tk.Toplevel(app.root)
        self.window.title(f"SSH terminal - {values['ssh.username']}@{values['ssh.host']}:{values['ssh.port']}")
        families = set(tkfont.families(self.window))
        family = next((name for name in ('Consolas', 'DejaVu Sans Mono', 'Menlo', 'Courier New')
                       if name in families), 'TkFixedFont')
        self.font = tkfont.Font(self.window, family=family, size=11)
        self.bold_font = tkfont.Font(self.window, family=family, size=11, weight='bold')
        self.cell_width = max(1, self.font.measure('0'))
        self.cell_height = max(1, self.font.metrics('linespace'))
        self.status = tk.StringVar(value='Connecting...')
        bar = ttk.Frame(self.window, padding=4)
        bar.pack(fill='x')
        ttk.Button(bar, text='Copy', command=self.copy).pack(side='left')
        ttk.Button(bar, text='Paste', command=self.paste).pack(side='left', padx=4)
        self.close_button = ttk.Button(bar, text='Disconnect', command=self.close_clicked)
        self.close_button.pack(side='left')
        ttk.Label(bar, textvariable=self.status).pack(side='left', padx=8)
        self.scrollbar = ttk.Scrollbar(self.window, orient='vertical', command=self.scroll_command)
        self.scrollbar.pack(side='right', fill='y')
        self.text = tk.Text(self.window, width=80, height=24, font=self.font, wrap='none', padx=0, pady=0,
                            borderwidth=0, highlightthickness=0, insertwidth=0, undo=False,
                            foreground=TERMINAL_FG, background=TERMINAL_BG, cursor='xterm',
                            selectbackground='#264f78', selectforeground='#ffffff')
        self.text.pack(fill='both', expand=True)
        self.text.tag_configure('cursor', foreground=TERMINAL_BG, background=TERMINAL_FG)
        self.tags = set()
        self.screen = TerminalScreen(80, 24, self.scrollback)
        self.screen.reply = self.reply
        self.stream = pyte.Stream(self.screen)
        self.stream.use_utf8 = False
        self.link = TerminalLink((80, 24, 0, 0))
        self.reset_view()
        self.text.bind('<Key>', self.key)
        self.text.bind('<Button-1>', lambda event: self.text.focus_set())
        self.text.bind('<Button-2>', lambda event: 'break')
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.text.bind(sequence, self.wheel)
            self.scrollbar.bind(sequence, self.wheel)
        self.text.bind('<Configure>', self.configured)
        self.window.bind('<Destroy>', self.destroyed)
        self.window.protocol('WM_DELETE_WINDOW', self.window_closed)
        self.window.minsize(320, 160)
        self.text.focus_set()
        self.pump_job = self.window.after(30, self.pump)
        threading.Thread(target=app.terminal_worker, args=(dict(values), self.link), daemon=True).start()

    def reply(self, data):
        self.link.send(('input', data.encode('utf-8')))

    def reset_view(self):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', '\n' * (self.screen.lines - 1))
        self.text.configure(state='disabled')
        self.history_view = False
        self.screen.dirty.update(range(self.screen.lines))
        self.render()
        self.text.xview_moveto(0)
        self.text.yview_moveto(0)

    def style_tag(self, char):
        fg = ANSI_COLORS.get(char.fg, '#' + char.fg if len(char.fg) == 6 else TERMINAL_FG)
        bg = ANSI_COLORS.get(char.bg, '#' + char.bg if len(char.bg) == 6 else TERMINAL_BG)
        if char.reverse:
            fg, bg = bg, fg
        key = (fg, bg, char.bold, char.underscore, char.strikethrough)
        name = 'style:' + ':'.join(map(str, key))
        if name not in self.tags:
            self.tags.add(name)
            options = {'foreground': fg, 'underline': char.underscore, 'overstrike': char.strikethrough,
                       'font': self.bold_font if char.bold else self.font}
            if bg != TERMINAL_BG:
                options['background'] = bg
            self.text.tag_configure(name, **options)
            self.text.tag_raise('sel')
            self.text.tag_raise('cursor')
        return name

    def runs(self, line):
        runs, last = [], None
        for x in range(self.screen.columns):
            char = line[x]
            if not char.data:
                continue
            tag = self.style_tag(char)
            if runs and tag == last:
                runs[-1][0].append(char.data)
            else:
                runs.append(([char.data], tag))
                last = tag
        return [(''.join(data), tag) for data, tag in runs]

    def put_row(self, y, runs):
        self.text.delete(f'{y + 1}.0', f'{y + 1}.end')
        for data, tag in runs:
            self.text.insert(f'{y + 1}.end', data, tag)

    def effective_offset(self):
        """Lines scrolled up; always 0 on the alternate screen and never beyond the history."""
        if self.screen.alt is not None:
            return 0
        self.offset = max(0, min(self.offset, len(self.screen.history)))
        return self.offset

    def update_scrollbar(self, offset):
        screen = self.screen
        total = len(screen.history) + screen.lines
        top = len(screen.history) - offset
        state = (0.0, 1.0) if screen.alt is not None else (top / total, (top + screen.lines) / total)
        if state != self.bar_state:
            self.bar_state = state
            self.scrollbar.set(*state)
            self.scrollbar.state(['disabled'] if screen.alt is not None else ['!disabled'])

    def render(self):
        screen, text = self.screen, self.text
        offset = self.effective_offset()
        self.update_scrollbar(offset)
        text.configure(state='normal')
        if offset:
            top = len(screen.history) - offset
            stamp = screen.history_total - len(screen.history) + top  # absolute index of first row
            if not self.history_view or offset < screen.lines or stamp != self.rendered_top:
                for y in range(screen.lines):
                    index = top + y
                    if index < len(screen.history):
                        self.put_row(y, [(data, self.style_tag(style)) for data, style in screen.history[index]])
                    else:
                        self.put_row(y, self.runs(screen.buffer[index - len(screen.history)]))
                text.tag_remove('cursor', '1.0', 'end')
            self.history_view, self.rendered_top = True, stamp
            screen.dirty.clear()
            text.configure(state='disabled')
            return
        if self.history_view:
            self.history_view = False
            screen.dirty.update(range(screen.lines))
        dirty = sorted(y for y in screen.dirty if 0 <= y < screen.lines)
        screen.dirty.clear()
        for y in dirty:
            self.put_row(y, self.runs(screen.buffer[y]))
        text.tag_remove('cursor', '1.0', 'end')
        cursor = screen.cursor
        if not cursor.hidden and 0 <= cursor.y < screen.lines:
            line, x = screen.buffer[cursor.y], min(cursor.x, screen.columns - 1)
            index = sum(1 for column in range(x) if line[column].data)
            text.tag_add('cursor', f'{cursor.y + 1}.{index}', f'{cursor.y + 1}.{index + 1}')
        text.configure(state='disabled')

    def schedule_render(self):
        if self.render_job is None:
            self.render_job = self.window.after(15, self.flush_render)

    def flush_render(self):
        self.render_job = None
        self.render()

    def scroll_to(self, top):
        """Show history starting at row `top` (0 = oldest retained line) of history + screen."""
        if self.screen.alt is None:
            self.offset = len(self.screen.history) - max(0, min(top, len(self.screen.history)))
            self.schedule_render()

    def scroll_command(self, *args):
        screen = self.screen
        if screen.alt is not None:
            return
        top = len(screen.history) - self.effective_offset()
        if args[0] == 'moveto':
            top = round(float(args[1]) * (len(screen.history) + screen.lines))
        elif args[0] == 'scroll':
            step = 1 if args[2] == 'units' else max(1, screen.lines - 1)
            top += int(float(args[1])) * step
        self.scroll_to(top)

    def wheel(self, event):
        if event.num == 4:
            notches = 1
        elif event.num == 5:
            notches = -1
        else:
            notches = event.delta / 120 if abs(event.delta) >= 120 else (event.delta > 0) - (event.delta < 0)
        if self.screen.alt is None and notches:
            lines = max(1, round(abs(notches) * 3))
            top = len(self.screen.history) - self.effective_offset()
            self.scroll_to(top - lines if notches > 0 else top + lines)
        return 'break'

    def scroll_to_bottom(self):
        if self.offset:
            self.offset = 0
            self.render()

    def feed(self, data):
        try:
            self.stream.feed(self.decoder.decode(data))
        except Exception:
            self.stream = pyte.Stream(self.screen)
            self.stream.use_utf8 = False
        added, self.seen_total = self.screen.history_total - self.seen_total, self.screen.history_total
        if self.offset and added:
            self.offset += added  # keep the viewed lines in place; clamped when evicted

    def pump(self):
        self.pump_job = None
        events = self.link.drain()
        data = bytearray()
        for event in events:
            if event[0] == 'data':
                data += event[1]
            elif event[0] == 'connected' and self.state == 'connecting':
                self.state = 'connected'
                self.status.set('Connected.')
            elif event[0] == 'end':
                if data:
                    self.feed(bytes(data))
                    data.clear()
                self.finish(event[1])
                return
        if data:
            self.feed(bytes(data))
        if self.screen.dirty or data:
            self.render()
        self.pump_job = self.window.after(10 if events else 30, self.pump)

    def finish(self, message):
        self.state = 'ended'
        self.screen.exit_alternate()
        self.feed(f'\r\n[{message}]\r\n'.encode('utf-8'))
        self.render()
        self.status.set(message)
        self.close_button.configure(text='Close')
        self.app.terminal_finished(self, message)
        if self.destroy_on_end:
            self.destroy()

    def configured(self, event):
        if self.resize_job is not None:
            self.window.after_cancel(self.resize_job)
        self.resize_job = self.window.after(60, self.apply_size)

    def apply_size(self):
        self.resize_job = None
        width, height = self.text.winfo_width(), self.text.winfo_height()
        columns, lines = max(10, width // self.cell_width), max(3, height // self.cell_height)
        if (columns, lines) == (self.screen.columns, self.screen.lines):
            return
        self.screen.resize(lines, columns)
        self.reset_view()
        self.link.size = (columns, lines, width, height)
        self.link.send(('resize',) + self.link.size)

    def key(self, event):
        state = event.state
        if state & CONTROL_MASK and state & SHIFT_MASK and event.keysym in ('C', 'c'):
            self.copy()
        elif state & CONTROL_MASK and state & SHIFT_MASK and event.keysym in ('V', 'v'):
            self.paste()
        elif self.state == 'connected':
            text = translate_key(event.keysym, event.char, state, self.screen.application_cursor)
            if text:
                self.scroll_to_bottom()
                self.link.send(('input', text.encode('utf-8')))
        return 'break'

    def copy(self):
        try:
            text = self.text.get('sel.first', 'sel.last')
        except tk.TclError:
            self.status.set('Select text with the mouse first.')
            return
        self.window.clipboard_clear()
        self.window.clipboard_append('\n'.join(line.rstrip() for line in text.split('\n')))
        self.text.focus_set()

    def paste(self):
        if self.state != 'connected':
            return
        try:
            clipboard = self.window.clipboard_get()
        except tk.TclError:
            return
        data, multiline = paste_payload(clipboard, self.screen.bracketed_paste)
        if multiline:
            preview = '\n'.join(line[:100] for line in clipboard.splitlines()[:10])
            if not messagebox.askyesno('Paste multiple lines', 'This text contains line breaks and may '
                                       f'execute remote commands. Paste it?\n\n{preview}', parent=self.window):
                self.text.focus_set()
                return
        if data:
            self.scroll_to_bottom()
            self.link.send(('input', data.encode('utf-8')))
        self.text.focus_set()

    def request_close(self):
        if self.state in ('connecting', 'connected'):
            self.state = 'closing'
            self.status.set('Disconnecting...')
            self.link.close()

    def close_clicked(self):
        if self.state == 'ended':
            self.destroy()
        else:
            self.request_close()

    def window_closed(self):
        self.destroy_on_end = True
        if self.state == 'ended':
            self.destroy()
        else:
            self.request_close()

    def destroyed(self, event):
        if event.widget is self.window:
            for job in (self.pump_job, self.resize_job, self.render_job):
                if job is not None:
                    self.window.after_cancel(job)
            self.pump_job = self.resize_job = self.render_job = None

    def destroy(self):
        if self.window.winfo_exists():
            self.window.destroy()


class App:
    def __init__(self, root):
        self.root = root
        root.title('Retro Selector - MAME / SNES / Mega Drive - SSH / SCP')
        root.geometry('1450x950')
        root.minsize(1100, 760)
        found = {}
        try:
            if CONFIG.exists():
                found = parse_properties(CONFIG.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError) as error:
            messagebox.showwarning('Configuration', str(error))
        values = resolve_config(found)
        self.v = {key: tk.StringVar(value=value) for key, value in values.items()}
        if values['ssh.save_credentials'] != 'true':
            self.v['ssh.password'].set('')
            self.v['ssh.key_passphrase'].set('')
        self.busy = False
        self.terminal = None
        self.events = queue.Queue()
        self.settings, self.combos, self.sample_widgets = [], [], []
        self.active_profile = self.v['emulator.active'].get()
        self.roms, self.filtered, self.remote = [], [], []
        self.marks, self.remote_marks = set(), set()
        self.loaded = self.remote_target = None
        self.page, self.job = 0, None
        self.generation, self.auto_job = 0, None
        self.space = tk.StringVar(value=SPACE_NOT_LOADED)
        self.images, self.cards, self.remote_rows = [], {}, {}
        self.search, self.remote_search = tk.StringVar(), tk.StringVar()
        self.count, self.remote_count = tk.StringVar(), tk.StringVar()
        self.status, self.pages = tk.StringVar(value='Ready'), tk.StringVar()
        self.build()
        for key in ('ssh.host', 'ssh.port', 'ssh.username', 'ssh.remote_dir',
                    'samples.remote_dir', 'snes.remote_dir', 'megadrive.remote_dir',
                    'ssh.remote_listing_mode'):
            self.v[key].trace_add('write', self.invalidate_remote)
        self.v['content.mode'].trace_add('write', self.content_changed)
        self.v['emulator.active'].trace_add('write', self.profile_changed)
        self.search.trace_add('write', self.schedule_filter)
        self.remote_search.trace_add('write', lambda *args: self.render_remote())
        self.auth_state()
        self.profile_state()
        self.update_titles()
        self.load()
        self.render_remote()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def emulator(self):
        return self.v['emulator.active'].get()

    def source_key(self):
        return active_keys(self.v['content.mode'].get(), self.emulator())[0]

    def noun(self):
        return 'ZIPs' if self.emulator() == 'mame' else 'files'

    def label(self, path):
        return path.stem if self.emulator() == 'mame' else path.name

    def update_titles(self):
        if self.emulator() != 'mame':
            label = f'{EMULATOR_NAMES[self.emulator()]} ROMs'
        else:
            label = 'MAME Samples' if self.v['content.mode'].get() == 'samples' else 'MAME ROMs'
        self.local_panel.configure(text=f'Local {label}')
        self.remote_panel.configure(text=f'Remote {label}')
        self.tree.heading('name', text='Remote ZIP filename' if self.emulator() == 'mame' else 'Remote filename')

    def profile_state(self):
        """Samples belong to MAME only: their controls are hidden for SNES (settings are kept)."""
        current = (self.emulator(), self.v['content.mode'].get() if self.emulator() == 'mame' else None)
        for (profile, mode), widgets in self.profile_rows.items():
            for widget in widgets:
                if profile == current[0] and mode in (None, current[1]):
                    widget.grid()
                else:
                    widget.grid_remove()
        enabled = not self.busy and self.emulator() == 'mame'
        for widget in self.sample_widgets:
            widget.configure(state=('readonly' if isinstance(widget, ttk.Combobox) else 'normal')
                             if enabled else 'disabled')

    def profile_changed(self, *args):
        if self.busy:
            if self.emulator() != self.active_profile:
                self.v['emulator.active'].set(self.active_profile)
            return
        self.active_profile = self.emulator()
        self.mode_changed()
        self.auto_refresh()

    def content_changed(self, *args):
        self.mode_changed()
        self.auto_refresh()

    def cancel_filter(self):
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None

    def mode_changed(self, *args):
        self.profile_state()
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
        config.columnconfigure(0, weight=1, uniform='columns')
        config.columnconfigure(1, weight=1, uniform='columns')
        left, right = ttk.LabelFrame(config, text='SSH connection (shared)', padding=6), \
            ttk.LabelFrame(config, text='Emulator profile', padding=6)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        right.grid(row=0, column=1, sticky='nsew', padx=(5, 0))
        for column in (left, right):
            column.columnconfigure(1, weight=1)
        self.entries = {}
        self.profile_rows = {('mame', None): [], ('mame', 'roms'): [], ('mame', 'samples'): [], ('snes', None): [], ('megadrive', None): []}
        left_fields = [('SSH host / IP:', 'ssh.host'), ('SSH port:', 'ssh.port'), ('User:', 'ssh.username'),
                       ('Authentication:', 'ssh.auth_mode'), ('Password:', 'ssh.password'),
                       ('Private key:', 'ssh.private_key'), ('Key passphrase:', 'ssh.key_passphrase'),
                       ('Remote listing:', 'ssh.remote_listing_mode'),
                       ('Terminal scrollback lines:', SCROLLBACK_KEY)]
        # (label, key, (emulator, MAME content) it is shown for; None = always visible; rows 2-3 are shared)
        right_fields = [('Emulator:', 'emulator.active', None, 0),
                        ('MAME content:', 'content.mode', ('mame', None), 1),
                        ('Local MAME ROMs:', 'rom.source', ('mame', 'roms'), 2),
                        ('Local MAME samples:', 'samples.source', ('mame', 'samples'), 2),
                        ('Local SNES ROMs:', 'snes.rom.source', ('snes', None), 2),
                        ('Local Mega Drive ROMs:', 'megadrive.rom.source', ('megadrive', None), 2),
                        ('Remote MAME ROMs:', 'ssh.remote_dir', ('mame', 'roms'), 3),
                        ('Remote MAME samples:', 'samples.remote_dir', ('mame', 'samples'), 3),
                        ('Remote SNES ROMs:', 'snes.remote_dir', ('snes', None), 3),
                        ('Remote Mega Drive ROMs:', 'megadrive.remote_dir', ('megadrive', None), 3)]
        browse_keys = ('rom.source', 'samples.source', 'snes.rom.source', 'megadrive.rom.source')

        def field(parent, row, label, key):
            name = ttk.Label(parent, text=label)
            name.grid(row=row, column=0, sticky='w', padx=8, pady=2)
            if key in ENUM_KEYS:
                widget = ttk.Combobox(parent, textvariable=self.v[key], values=ENUM_KEYS[key], state='readonly')
                self.combos.append(widget)
                if key == 'ssh.auth_mode':
                    widget.bind('<<ComboboxSelected>>', lambda event: self.auth_state())
            else:
                widget = ttk.Entry(parent, textvariable=self.v[key],
                                   show='*' if key in ('ssh.password', 'ssh.key_passphrase') else '')
                self.settings.append(widget)
            widget.grid(row=row, column=1, sticky='ew', pady=2)
            self.entries[key] = widget
            buttons = []
            if key in browse_keys:
                widget.bind('<Return>', lambda event: self.load())
                button = ttk.Button(parent, text='Browse...', command=lambda k=key: self.browse_source(k))
                button.grid(row=row, column=2, padx=8)
                self.settings.append(button)
                buttons.append(button)
            elif key == 'ssh.private_key':
                self.key_browse = ttk.Button(parent, text='Browse...', command=self.browse_key)
                self.key_browse.grid(row=row, column=2, padx=8)
                self.settings.append(self.key_browse)
            return [name, widget] + buttons

        for row, (label, key) in enumerate(left_fields):
            field(left, row, label, key)
        for label, key, profile, row in right_fields:
            parts = field(right, row, label, key)
            if profile:
                self.profile_rows[profile].extend(parts)
            if key in ('content.mode', 'samples.source', 'samples.remote_dir'):
                self.sample_widgets.append(self.entries[key])
            if key == 'samples.source':
                self.sample_widgets.append(parts[2])
        row = len(left_fields)
        for key, label in [('ssh.legacy_rsa', 'Allow legacy SSH RSA (SHA-1)'),
                           ('ssh.save_credentials', 'Save credentials in .properties (plain text)')]:
            check = ttk.Checkbutton(left, text=label, variable=self.v[key], onvalue='true', offvalue='false')
            check.grid(row=row, column=1, columnspan=2, sticky='w')
            self.settings.append(check)
            row += 1
        actions = ttk.Frame(config)
        actions.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        for text, command in (('Load', self.load), ('Save', self.save)):
            button = ttk.Button(actions, text=text, command=command)
            button.pack(side='left', padx=8)
            self.settings.append(button)
        self.terminal_button = ttk.Button(actions, text='>_ SSH terminal', command=self.open_terminal)
        self.terminal_button.pack(side='left', padx=8)
        ttk.Label(actions, text='ssh: POSIX shell / sftp: SFTP subsystem').pack(side='left', padx=8)
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
        ttk.Label(right, textvariable=self.space, padding=(8, 0)).pack(anchor='w')
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
        self.terminal_button.configure(state='disabled' if busy else 'normal')
        self.auth_state()
        self.profile_state()
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

    def values(self, terminal=False, scrollback=False):
        values = {key: var.get() for key, var in self.v.items()}
        if terminal or scrollback:
            values[SCROLLBACK_KEY] = str(parse_scrollback(values[SCROLLBACK_KEY]))
        for key in ('rom.source', 'samples.source', 'snes.rom.source', 'megadrive.rom.source', 'ssh.host',
                    'ssh.port', 'ssh.username', 'ssh.remote_dir', 'samples.remote_dir', 'snes.remote_dir',
                    'megadrive.remote_dir', 'ssh.private_key'):
            values[key] = values[key].strip()
        if terminal:
            values = {key: values[key] for key in CONNECTION_KEYS + (SCROLLBACK_KEY,)}
        if any('\n' in value or '\r' in value or '\0' in value for value in values.values()):
            raise ValueError('Values cannot contain line breaks or NUL characters.')
        if not terminal:
            if values['emulator.active'] not in EMULATORS:
                raise ValueError('Invalid emulator.')
            source_key, remote_key = active_keys(values['content.mode'], values['emulator.active'])
            if not values[source_key] or not local(values[source_key]).is_dir():
                raise ValueError(f"Select an existing {self.profile_name(values)} source directory.")
        if not values['ssh.host'] or not values['ssh.username']:
            raise ValueError('Enter host and username.')
        port = int(values['ssh.port'])
        if not 1 <= port <= 65535:
            raise ValueError('Invalid SSH port.')
        values['ssh.port'] = str(port)
        if not terminal and not values[remote_key].startswith('/'):
            raise ValueError('Use an absolute remote directory for the selected content.')
        if values['ssh.auth_mode'] not in ('password', 'key') or (
                not terminal and values['ssh.remote_listing_mode'] not in ('ssh', 'sftp')):
            raise ValueError('Invalid mode.')
        if values['ssh.auth_mode'] == 'key':
            path = local(values['ssh.private_key'])
            if not values['ssh.private_key'] or not path.is_file() or path.suffix.lower() == '.pub':
                raise ValueError('Select an existing private key, not a .pub file.')
        if not terminal:
            values['operation.emulator'] = values['emulator.active']
            values['operation.source'] = values[source_key]
            values['operation.remote_dir'] = values[remote_key]
        return values

    @staticmethod
    def profile_name(values):
        if values['emulator.active'] != 'mame':
            return f"{EMULATOR_NAMES[values['emulator.active']]} ROMs"
        return 'MAME samples' if values['content.mode'] == 'samples' else 'MAME ROMs'

    def save(self):
        try:
            values = self.values(scrollback=True)
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
            extensions = profile_extensions(self.emulator())
            roms = sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in extensions),
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
        self.status.set(f"Loaded {len(roms)} local {self.profile_name(self.values_snapshot())} files.")

    def values_snapshot(self):
        return {'emulator.active': self.emulator(), 'content.mode': self.v['content.mode'].get()}

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
            ttk.Label(self.grid, text=f'No matching {self.noun()}.', padding=20).grid(row=0, column=0, columnspan=4)
        for index, path in enumerate(visible):
            try:
                with Image.open(path.with_suffix('.png')) as source:
                    image = ImageOps.exif_transpose(source).convert('RGBA')
                    image.thumbnail((150, 110), Image.Resampling.LANCZOS)
            except (OSError, ValueError, Image.DecompressionBombError):
                if self.emulator() == 'mame' and self.v['content.mode'].get() == 'samples':
                    image = sample_placeholder()
                else:
                    image = emulator_placeholder(self.emulator())
                    image.thumbnail((150, 110), Image.Resampling.LANCZOS)
            background = Image.new('RGBA', (150, 110), '#eee')
            background.alpha_composite(image, ((150 - image.width) // 2, (110 - image.height) // 2))
            photo = ImageTk.PhotoImage(background.convert('RGB'))
            self.images.append(photo)
            card = tk.Frame(self.grid, bd=2, relief='solid')
            card.grid(row=index // 4, column=index % 4, padx=4, pady=4, sticky='nsew')
            variable = tk.BooleanVar(value=path in self.marks)
            check = tk.Checkbutton(card, text=self.label(path), variable=variable, wraplength=145,
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
        self.count.set(f'{len(self.filtered)} / {len(self.roms)} {self.noun()} | {len(self.marks)} selected ({hidden} outside filter)')
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
        emulator = self.emulator()
        mode = self.v['content.mode'].get() if emulator == 'mame' else ''
        remote_key = active_keys(mode, emulator)[1]
        return (emulator, mode) + tuple(self.v[key].get().strip() for key in
                     ('ssh.host', 'ssh.port', 'ssh.username', remote_key, 'ssh.remote_listing_mode'))

    def invalidate_remote(self, *args):
        self.generation += 1
        self.remote, self.remote_target = [], None
        self.remote_marks.clear()
        self.space.set(SPACE_NOT_LOADED)
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
        self.remote_count.set(f'{len(names)} / {len(self.remote)} {self.noun()} | {len(self.remote_marks)} marked ({hidden} outside filter)'
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

    def auto_refresh(self):
        if self.auto_job is not None:
            self.root.after_cancel(self.auto_job)
        self.auto_job = self.root.after(50, self.run_auto_refresh)

    def run_auto_refresh(self):
        self.auto_job = None
        if not self.busy and self.terminal is None:
            self.refresh(automatic=True)

    def refresh(self, automatic=False):
        if self.busy:
            return
        try:
            values = self.values()
            if automatic and values['ssh.auth_mode'] == 'password' and not values['ssh.password']:
                raise ValueError('Enter the SSH password')
        except (OSError, ValueError) as error:
            if automatic:
                self.status.set(f'Remote list not loaded automatically: {error}. Click Refresh.')
            else:
                messagebox.showerror('Configuration', str(error))
            return
        self.set_busy(True)
        self.space.set(SPACE_LOADING)
        self.status.set('Loading remote list...')
        threading.Thread(target=self.list_worker, args=(values, self.signature(), self.generation, automatic),
                         daemon=True).start()

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

    @staticmethod
    async def space_async(connection, directory, sftp=None):
        """Available/total bytes of the filesystem holding directory, or None; never raises."""
        if sftp is not None:
            try:
                space = vfs_space(await asyncio.wait_for(sftp.statvfs(directory), 20))
                if space:
                    return space
            except Exception:
                pass
        try:
            response = await connection.run(f'df -Pk {shlex.quote(directory)}', check=False, timeout=20)
            return parse_df(response.stdout) if response.exit_status == 0 else None
        except Exception:
            return None

    async def list_async(self, values):
        directory = values['operation.remote_dir']
        extensions = profile_extensions(values['operation.emulator'])
        async with await self.connect(values) as connection:
            if values['ssh.remote_listing_mode'] == 'sftp':
                result = []
                async with connection.start_sftp_client() as sftp:
                    for name in await sftp.listdir(directory):
                        if not name.lower().endswith(extensions):
                            continue
                        attrs = await sftp.stat(posixpath.join(directory, name))
                        if self.regular(attrs):
                            result.append(name)
                    space = await self.space_async(connection, directory, sftp)
            else:
                command = (f'directory={shlex.quote(directory)}; '
                    '[ -d "$directory" ] || { printf "%s\\n" "Directory not found" >&2; exit 1; }; '
                    '[ -r "$directory" ] && [ -x "$directory" ] || { printf "%s\\n" "Directory not accessible" >&2; exit 1; }; '
                    'for path in "$directory"/*; do [ -f "$path" ] || continue; '
                    'case "$path" in ' + shell_patterns(extensions) + ') printf "%s\\000" "${path##*/}" ;; esac; done; exit 0')
                response = await connection.run(command, check=True, timeout=60)
                result = [name for name in response.stdout.split('\0') if name]
                space = await self.space_async(connection, directory)
            return sorted(result, key=str.casefold), space

    @staticmethod
    def regular(attrs):
        return ((attrs.permissions is not None and stat.S_ISREG(attrs.permissions))
                or (attrs.permissions is None and attrs.type == 1))

    def list_worker(self, values, target, generation, automatic=False):
        try:
            names, space = asyncio.run(asyncio.wait_for(self.list_async(values), 180))
            self.events.put(('listed', names, target, generation, space))
        except Exception as error:
            self.events.put(('list_error', f'{type(error).__name__}: {error}', generation, automatic))

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
            extensions = profile_extensions(values['operation.emulator'])
            for name in files:
                if (not name.lower().endswith(extensions) or '/' in name or '\\' in name
                        or any(ord(character) < 32 for character in name)):
                    raise ValueError(f'Unsafe filename: {name!r}')
        except (OSError, ValueError) as error:
            messagebox.showerror('Deletion configuration', str(error))
            return
        self.start_batch(files, values, True)

    def start_batch(self, files, values, deleting):
        action = 'Delete permanently' if deleting else 'Copy'
        warning = ('Permanent remote deletion. Local files are not modified.' +
                   ('\nBIOS and parent ZIPs may be required by other games.'
                    if values['operation.emulator'] == 'mame' else '') if deleting
                   else 'Existing remote files may be overwritten.')
        text = (f"Profile: {self.profile_name(values)}\n{action} {len(files)} files\n"
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

    def open_terminal(self):
        if self.busy or self.terminal is not None:
            return
        try:
            values = self.values(terminal=True)
        except (OSError, ValueError) as error:
            messagebox.showerror('SSH terminal', str(error))
            return
        self.set_busy(True)
        try:
            self.terminal = TerminalWindow(self, values)
        except Exception:
            self.terminal = None
            self.set_busy(False)
            raise
        self.status.set('SSH terminal open; file operations and configuration are locked.')

    def terminal_finished(self, window, message):
        if self.terminal is window:
            self.terminal = None
            self.invalidate_remote()
            self.set_busy(False)
            self.status.set(f'SSH terminal closed. Remote list invalidated. ({message})')

    def terminal_worker(self, values, link):
        reason = 'Terminal worker failed.'
        try:
            reason = asyncio.run(self.terminal_async(values, link))
        except BaseException as error:
            reason = f'{type(error).__name__}: {error}'
        link.out.put(('end', reason))

    async def terminal_async(self, values, link):
        connection = process = None
        reason = 'Disconnected.'
        try:
            link.attach(asyncio.get_running_loop(), asyncio.current_task(), asyncio.Queue())
            connection = await self.connect(values)
            columns, lines, width, height = size = link.size
            process = await connection.create_process(term_type=TERM_TYPE, term_size=(columns, lines, width, height),
                                                      encoding=None, request_pty='force')
            if link.size != size:
                process.change_terminal_size(*link.size)
            link.out.put(('connected',))
            tasks = [asyncio.ensure_future(self.terminal_reader(process, link)),
                     asyncio.ensure_future(self.terminal_writer(process, link))]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            for task in tasks:
                if task.done() and not task.cancelled() and task.exception():
                    raise task.exception()
            reason = 'Remote session ended.'
            try:
                await asyncio.wait_for(process.wait_closed(), 5)
                if process.exit_status is not None:
                    reason = f'Remote session ended (exit status {process.exit_status}).'
            except Exception:
                pass
        except asyncio.CancelledError:
            pass
        except Exception as error:
            reason = f'{type(error).__name__}: {error}'
        finally:
            try:
                if process is not None:
                    process.close()
                if connection is not None:
                    connection.close()
                    await asyncio.wait_for(connection.wait_closed(), 5)
            except (Exception, asyncio.CancelledError):
                pass
        return reason

    @staticmethod
    async def terminal_reader(process, link):
        while True:
            while link.pending > OUTPUT_LIMIT:
                await asyncio.sleep(0.02)
            data = await process.stdout.read(65536)
            if not data:
                return
            link.put_data(data)

    @staticmethod
    async def terminal_writer(process, link):
        inbox = link.inbox
        while True:
            item = await inbox.get()
            if item[0] == 'input':
                process.stdin.write(item[1])
                await process.stdin.drain()
            elif item[0] == 'resize':
                process.change_terminal_size(*item[1:])

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
                    _, names, target, generation, space = event
                    current = generation == self.generation and target == self.signature()
                    if current:
                        self.remote, self.remote_target = names, target
                        self.space.set(format_space(space))
                        self.render_remote()
                    else:
                        self.space.set(SPACE_NOT_LOADED)
                    self.set_busy(False)
                    self.status.set('Remote list refreshed.' if current else 'Remote list discarded: settings changed.')
                elif kind == 'list_error':
                    _, message, generation, automatic = event
                    current = generation == self.generation
                    if current:
                        self.invalidate_remote()
                    else:
                        self.space.set(SPACE_NOT_LOADED)
                    self.set_busy(False)
                    self.status.set(f'Remote listing failed: {message}' if automatic and current
                                    else 'Remote listing failed.' if current else 'Remote list discarded: settings changed.')
                    if not automatic and current:
                        messagebox.showerror('Remote listing', message)
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
        text = 'Retro Selector\nCopyright (C) 2026 David González López-Tercero\nGNU GPL version 3 or later. WITHOUT ANY WARRANTY.\n\n'
        try:
            text += (BASE / 'LICENSE').read_text(encoding='utf-8')
        except OSError:
            text += 'See LICENSE or https://www.gnu.org/licenses/gpl-3.0.html'
        self.report('About / License', text)

    def close(self):
        if self.terminal is not None:
            messagebox.showwarning('SSH terminal active', 'Disconnect the SSH terminal before closing.')
            return
        if self.busy:
            messagebox.showwarning('Operation in progress', 'Wait for the operation to finish.')
            return
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
