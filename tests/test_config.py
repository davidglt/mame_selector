import fnmatch
import unittest
from pathlib import Path

from support import TempBaseCase, rs

ROM_NAMES = ('Sonic.BIN', 'a.Md', 'b.GEN', 'c.smd', 'd.ZIP')
COMPANION_NAMES = ('a.srm', 'a.sav', 'a.state', 'a.cue', 'a.iso', 'a.32x', 'a.sfc', 'a.png', 'bin', 'a.bin.srm')


class ParseConfigTests(TempBaseCase):
    def test_parse_ignores_comments_unknown_keys_and_keeps_values_literal(self):
        found = rs.parse_properties('# c\n! c\n\nunknown=1\n  ssh.host = h \nmegadrive.rom.source=roms_md/\nnoequals\n')
        self.assertEqual(found, {'ssh.host': ' h ', 'megadrive.rom.source': 'roms_md/'})

    def test_resolve_applies_defaults_for_all_profiles(self):
        values = rs.resolve_config({})
        self.assertEqual(values, rs.DEFAULTS)
        self.assertEqual(values['rom.source'], 'roms_mame/')

    def test_existing_mame_and_snes_values_survive_unchanged(self):
        found = rs.parse_properties('rom.source=mine/\nssh.remote_dir=/r/\nsamples.source=s/\n'
                                    'snes.rom.source=sn/\nsnes.remote_dir=/sn/\ncontent.mode=samples\nemulator.active=snes\n')
        values = rs.resolve_config(found)
        for key, expected in (('rom.source', 'mine/'), ('ssh.remote_dir', '/r/'), ('samples.source', 's/'),
                              ('snes.rom.source', 'sn/'), ('snes.remote_dir', '/sn/'),
                              ('content.mode', 'samples'), ('emulator.active', 'snes')):
            self.assertEqual(values[key], expected)
        self.assertEqual(values['megadrive.rom.source'], 'roms_md/')
        self.assertEqual(values['megadrive.remote_dir'], '/var/mobile/Media/ROMs/MD.emu/roms/')

    def test_legacy_rom_source_fallback(self):
        self.assertEqual(rs.resolve_config(rs.parse_properties('ssh.host=h\n'))['rom.source'], 'roms/')
        for text in ('emulator.active=mame\n', 'snes.remote_dir=/x/\n', 'megadrive.remote_dir=/x/\n',
                     'megadrive.rom.source=m/\n', 'rom.source=keep/\n'):
            values = rs.resolve_config(rs.parse_properties('ssh.host=h\n' + text))
            self.assertEqual(values['rom.source'], 'keep/' if 'keep' in text else 'roms_mame/', text)
        for empty in ('', '# only a comment\n', 'unknown=1\n'):
            self.assertEqual(rs.resolve_config(rs.parse_properties(empty))['rom.source'], 'roms_mame/')

    def test_invalid_enum_values_fall_back_to_defaults(self):
        values = rs.resolve_config({'emulator.active': 'sega', 'content.mode': 'x', 'ssh.auth_mode': 'x',
                                    'ssh.remote_listing_mode': 'x'})
        self.assertEqual([values[k] for k in ('emulator.active', 'content.mode', 'ssh.auth_mode', 'ssh.remote_listing_mode')],
                         ['mame', 'roms', 'password', 'ssh'])
        self.assertEqual(rs.resolve_config({'emulator.active': 'megadrive'})['emulator.active'], 'megadrive')

    def test_example_file_matches_defaults_and_has_no_credentials(self):
        example = Path(__file__).resolve().parent.parent / 'retro_selector.properties.example'
        found = rs.parse_properties(example.read_text(encoding='utf-8'))
        self.assertEqual(set(found), set(rs.DEFAULTS))
        self.assertEqual(found['megadrive.rom.source'], 'roms_md/')
        self.assertEqual(found['megadrive.remote_dir'], '/var/mobile/Media/ROMs/MD.emu/roms/')
        self.assertEqual(found['emulator.active'], 'mame')
        for key in ('ssh.password', 'ssh.private_key', 'ssh.key_passphrase'):
            self.assertEqual(found[key], '')
        self.assertEqual(found['ssh.save_credentials'], 'false')

    def test_local_resolves_relative_to_base_and_keeps_absolute(self):
        self.assertEqual(rs.local(' roms_md/ '), (self.base / 'roms_md').resolve())
        self.assertEqual(rs.local(str(self.base / 'x')), (self.base / 'x').resolve())

    def test_atomic_write_replaces_content_and_leaves_no_temporary(self):
        target = self.base / 'f.properties'
        rs.atomic_write(target, 'a=1\n')
        rs.atomic_write(target, 'a=2\n')
        self.assertEqual(target.read_text(encoding='utf-8'), 'a=2\n')
        self.assertEqual([p.name for p in self.base.iterdir()], ['f.properties'])

    def test_parse_scrollback(self):
        self.assertEqual(rs.parse_scrollback(' 500 '), 500)
        for bad in ('0', '-1', 'abc', '1.5', '', '1\n2', '9' * 41, '١٢'):
            with self.assertRaises(ValueError, msg=bad):
                rs.parse_scrollback(bad)


class ProfileTests(unittest.TestCase):
    def test_each_profile_maps_to_its_own_source_and_destination(self):
        keys = {rs.active_keys('roms', 'mame'), rs.active_keys('samples', 'mame'),
                rs.active_keys('roms', 'snes'), rs.active_keys('roms', 'megadrive')}
        self.assertEqual(len(keys), 4)
        self.assertEqual(rs.active_keys('samples', 'snes'), rs.active_keys('roms', 'snes'))
        self.assertEqual(rs.active_keys('x', 'megadrive'), ('megadrive.rom.source', 'megadrive.remote_dir'))
        for bad in (('roms', 'sega'), ('other', 'mame')):
            with self.assertRaises(ValueError):
                rs.active_keys(*bad)

    def accepted(self, emulator):
        extensions = rs.profile_extensions(emulator)
        return {name for name in ROM_NAMES + COMPANION_NAMES if name.lower().endswith(extensions)}

    def test_megadrive_accepts_cartridge_roms_and_rejects_saves_and_other_systems(self):
        self.assertEqual(self.accepted('megadrive'), set(ROM_NAMES))

    def test_mame_and_snes_filters_are_unchanged(self):
        self.assertEqual(self.accepted('mame'), {'d.ZIP'})
        self.assertEqual(self.accepted('snes'), {'a.sfc', 'd.ZIP'})

    def test_shell_patterns_match_same_names_as_python_filter(self):
        for emulator in ('mame', 'snes', 'megadrive'):
            patterns = rs.shell_patterns(rs.profile_extensions(emulator)).split('|')
            for name in ROM_NAMES + COMPANION_NAMES:
                matched = any(fnmatch.fnmatchcase('/dir/' + name, pattern) for pattern in patterns)
                self.assertEqual(matched, name in self.accepted(emulator), (emulator, name))

    def test_placeholders_are_distinct_per_profile_and_independent_copies(self):
        images = {emulator: rs.emulator_placeholder(emulator) for emulator in rs.EMULATORS}
        self.assertEqual({image.size for image in images.values()}, {(128, 128)})
        self.assertEqual(len({image.tobytes() for image in images.values()}), len(images))
        images['megadrive'].paste((1, 2, 3, 255), (0, 0, 128, 128))
        self.assertNotEqual(rs.emulator_placeholder('megadrive').tobytes(), images['megadrive'].tobytes())


class SpaceAndTerminalHelperTests(unittest.TestCase):
    def test_parse_df_and_format_space(self):
        text = 'Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/disk0s1s2 1000 400 600 40% /var\n'
        self.assertEqual(rs.parse_df(text), (600 * 1024, 1000 * 1024))
        self.assertIsNone(rs.parse_df('garbage'))
        self.assertEqual(rs.format_space(None), 'Disk space: unavailable')
        self.assertIn('60% free', rs.format_space(rs.parse_df(text)))

    def test_translate_key_and_paste_payload(self):
        self.assertEqual(rs.translate_key('Up', '', 0), '\x1b[A')
        self.assertEqual(rs.translate_key('Up', '', 0, application_cursor=True), '\x1bOA')
        self.assertEqual(rs.translate_key('c', 'c', rs.CONTROL_MASK), '\x03')
        self.assertEqual(rs.translate_key('a', 'a', 0), 'a')
        self.assertIsNone(rs.translate_key('Shift_L', '', 0))
        self.assertEqual(rs.paste_payload('a\r\nb\x07'), ('a\rb', True))
        self.assertEqual(rs.paste_payload('x', bracketed=True), (rs.PASTE_START + 'x' + rs.PASTE_END, False))

    def test_terminal_screen_scrollback_is_bounded(self):
        screen = rs.TerminalScreen(10, 2, scrollback=3)
        stream = rs.pyte.Stream(screen)
        stream.feed(''.join(f'line{i}\r\n' for i in range(10)))
        self.assertEqual(len(screen.history), 3)
        self.assertGreater(screen.history_total, 3)


if __name__ == '__main__':
    unittest.main()
