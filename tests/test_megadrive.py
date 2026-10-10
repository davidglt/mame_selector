import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import retro_selector as rs


class MegaDriveTests(unittest.TestCase):
    def test_defaults_and_names(self):
        self.assertEqual(rs.DEFAULTS['megadrive.rom.source'], 'roms_md/')
        self.assertEqual(rs.DEFAULTS['megadrive.remote_dir'], '/var/mobile/Media/ROMs/MD.emu/roms/')
        self.assertIn('megadrive', rs.EMULATORS)
        self.assertEqual(rs.EMULATOR_NAMES['megadrive'], 'Sega Mega Drive / Genesis')
        self.assertEqual(rs.resolve_config({'emulator.active': 'megadrive'})['emulator.active'], 'megadrive')

    def test_keys_and_extensions(self):
        self.assertEqual(rs.active_keys('roms', 'megadrive'), ('megadrive.rom.source', 'megadrive.remote_dir'))
        self.assertEqual(rs.profile_extensions('megadrive'), ('.bin', '.md', '.gen', '.smd', '.zip'))
        for name in ('game.srm', 'game.sav', 'game.state', 'game.cue', 'game.iso', 'game.32x'):
            self.assertFalse(name.lower().endswith(rs.profile_extensions('megadrive')))
        self.assertEqual(rs.profile_extensions('mame'), ('.zip',))
        self.assertEqual(rs.profile_extensions('snes'), rs.SNES_EXTENSIONS)

    def test_existing_configs_unchanged(self):
        self.assertEqual(rs.active_keys('samples', 'mame'), ('samples.source', 'samples.remote_dir'))
        legacy = rs.resolve_config(rs.parse_properties('ssh.host=h\n'))
        self.assertEqual(legacy['rom.source'], 'roms/')
        self.assertEqual(legacy['megadrive.rom.source'], 'roms_md/')
        new = rs.resolve_config(rs.parse_properties('megadrive.rom.source=x/\n'))
        self.assertEqual(new['rom.source'], 'roms_mame/')

    def test_invalid_emulator_falls_back(self):
        self.assertEqual(rs.resolve_config({'emulator.active': 'sega'})['emulator.active'], 'mame')
        with self.assertRaises(ValueError):
            rs.active_keys('roms', 'sega')

    def test_shell_patterns(self):
        self.assertIn('*.[bB][iI][nN]', rs.shell_patterns(rs.profile_extensions('megadrive')))

    def test_placeholder(self):
        self.assertEqual(rs.emulator_placeholder('megadrive').size, (128, 128))


if __name__ == '__main__':
    unittest.main()
