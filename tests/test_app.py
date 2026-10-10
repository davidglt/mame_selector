import io
import unittest
from unittest import mock

from PIL import Image

from support import AppCase, rs

MD_FILES = ('Sonic.BIN', 'alpha.md', 'Beta.GEN', 'gamma.smd', 'zeta.ZIP')
MD_NOISE = ('Sonic.srm', 'alpha.sav', 'x.state', 'disc.cue', 'disc.iso', 'x.32x', 'x.sfc', 'cover.png', 'README')


class LoadAndFilterTests(AppCase):
    def test_megadrive_lists_only_cartridge_roms_sorted_ignoring_saves_and_directories(self):
        folder = self.touch('roms_md', *MD_FILES, *MD_NOISE)
        (folder / 'folder.bin').mkdir()
        self.make_app('emulator.active=megadrive\n')
        self.assertEqual(self.local_names(), ['alpha.md', 'Beta.GEN', 'gamma.smd', 'Sonic.BIN', 'zeta.ZIP'])
        self.assertEqual(self.app.status.get(), 'Loaded 5 local Sega Mega Drive / Genesis ROMs files.')

    def test_mame_roms_snes_and_samples_keep_their_own_filters_and_folders(self):
        self.touch('roms_mame', 'pacman.zip', 'pacman.png', 'neo.bin', 'a.md')
        self.touch('samples_mame', 'dkong.zip', 'readme.txt')
        self.touch('roms_snes', 'z.sfc', 'a.SMC', 'b.fig', 'c.swc', 'd.zip', 'e.bin', 'f.md')
        self.make_app()
        self.assertEqual(self.local_names(), ['pacman.zip'])
        self.select('mame', 'samples')
        self.assertEqual(self.local_names(), ['dkong.zip'])
        self.select('snes')
        self.assertEqual(self.local_names(), ['a.SMC', 'b.fig', 'c.swc', 'd.zip', 'z.sfc'])

    def test_labels_use_stem_for_mame_and_full_name_otherwise(self):
        self.touch('roms_mame', 'pacman.zip')
        self.touch('roms_md', 'Sonic.bin')
        app = self.make_app()
        self.assertEqual(app.label(app.roms[0]), 'pacman')
        self.select('megadrive')
        self.assertEqual(app.label(app.roms[0]), 'Sonic.bin')

    def test_search_filters_by_stem_and_select_all_marks_only_matches(self):
        self.touch('roms_md', 'sonic.bin', 'sonic2.md', 'streets.gen')
        app = self.make_app('emulator.active=megadrive\n')
        app.search.set('sonic')
        app.filter()
        self.assertEqual([p.name for p in app.filtered], ['sonic.bin', 'sonic2.md'])
        app.select_all()
        self.assertEqual({p.name for p in app.marks}, {'sonic.bin', 'sonic2.md'})
        app.clear()
        self.assertFalse(app.marks)

    def test_missing_source_reports_error_and_clears_selection(self):
        self.touch('roms_md', 'a.bin')
        app = self.make_app('emulator.active=megadrive\n')
        app.select_all()
        app.v['megadrive.rom.source'].set('does_not_exist/')
        app.load()
        self.assertEqual((app.roms, app.filtered, app.marks), ([], [], set()))
        self.assertIn('Source directory not found', self.dialogs['showerror'].call_args[0][1])

    def test_reload_keeps_marks_for_files_still_present_only(self):
        folder = self.touch('roms_md', 'a.bin', 'b.bin')
        app = self.make_app('emulator.active=megadrive\n')
        app.select_all()
        (folder / 'b.bin').unlink()
        app.load()
        self.assertEqual({p.name for p in app.marks}, {'a.bin'})

    def test_covers_are_optional_and_unreadable_covers_fall_back_to_placeholder(self):
        folder = self.touch('roms_md', 'good.md', 'broken.md', 'none.md')
        buffer = io.BytesIO()
        Image.new('RGB', (300, 200), 'red').save(buffer, 'PNG')
        (folder / 'good.png').write_bytes(buffer.getvalue())
        (folder / 'broken.png').write_bytes(b'not a png')
        app = self.make_app('emulator.active=megadrive\n')
        self.assertEqual(len(app.images), 3)
        self.assertEqual(len(app.cards), 3)
        self.dialogs['showerror'].assert_not_called()

    def test_titles_and_nouns_follow_profile(self):
        app = self.make_app()
        self.assertEqual(app.local_panel.cget('text'), 'Local MAME ROMs')
        self.assertEqual(app.noun(), 'ZIPs')
        self.select('megadrive')
        self.assertEqual(app.local_panel.cget('text'), 'Local Sega Mega Drive / Genesis ROMs')
        self.assertEqual(app.remote_panel.cget('text'), 'Remote Sega Mega Drive / Genesis ROMs')
        self.assertEqual(app.noun(), 'files')
        self.select('mame', 'samples')
        self.assertEqual(app.remote_panel.cget('text'), 'Remote MAME Samples')


class ProfileSwitchingTests(AppCase):
    def test_switching_clears_marks_search_and_remote_state_and_loads_new_source(self):
        self.touch('roms_mame', 'pacman.zip')
        self.touch('roms_md', 'sonic.bin')
        app = self.make_app()
        app.select_all()
        app.remote, app.remote_target = ['old.zip'], app.signature()
        app.remote_marks.add('old.zip')
        app.search.set('pac')
        self.select('megadrive')
        self.assertEqual(self.local_names(), ['sonic.bin'])
        self.assertEqual((app.marks, app.remote, app.remote_marks, app.remote_target, app.search.get()),
                         (set(), [], set(), None, ''))
        self.select('mame')
        self.assertEqual(app.marks, set())

    def test_remote_signature_differs_per_profile_and_destination_edit_invalidates_listing(self):
        app = self.make_app()
        signatures = set()
        for emulator in ('mame', 'snes', 'megadrive'):
            self.select(emulator)
            signatures.add(app.signature())
        self.assertEqual(len(signatures), 3)
        for key in ('ssh.remote_dir', 'snes.remote_dir', 'megadrive.remote_dir'):
            emulator = {'ssh.remote_dir': 'mame', 'snes.remote_dir': 'snes', 'megadrive.remote_dir': 'megadrive'}[key]
            self.select(emulator)
            app.remote, app.remote_target = ['a.zip'], app.signature()
            app.v[key].set('/changed/')
            self.assertEqual((app.remote, app.remote_target), ([], None), key)

    def test_each_profile_shows_only_its_own_fields(self):
        app = self.make_app()
        self.root.update_idletasks()

        def visible():
            return {key for key, widget in app.entries.items() if widget.winfo_manager() == 'grid'}

        shared = {'emulator.active', 'ssh.host', 'ssh.port', 'ssh.username', 'ssh.auth_mode', 'ssh.password',
                  'ssh.private_key', 'ssh.key_passphrase', 'ssh.remote_listing_mode', rs.SCROLLBACK_KEY}
        expected = {('mame', 'roms'): {'content.mode', 'rom.source', 'ssh.remote_dir'},
                    ('mame', 'samples'): {'content.mode', 'samples.source', 'samples.remote_dir'},
                    ('snes', 'roms'): {'snes.rom.source', 'snes.remote_dir'},
                    ('megadrive', 'roms'): {'megadrive.rom.source', 'megadrive.remote_dir'}}
        for (emulator, mode), fields in expected.items():
            self.select(emulator, mode)
            self.assertEqual(visible(), shared | fields, (emulator, mode))

    def test_sample_controls_are_enabled_only_for_mame(self):
        app = self.make_app()
        self.assertEqual(str(app.entries['content.mode'].cget('state')), 'readonly')
        self.select('megadrive')
        self.assertEqual(str(app.entries['content.mode'].cget('state')), 'disabled')
        self.select('mame')
        self.assertEqual(str(app.entries['content.mode'].cget('state')), 'readonly')

    def test_profile_cannot_change_while_busy(self):
        self.touch('roms_md', 'a.bin')
        app = self.make_app('emulator.active=megadrive\n')
        app.set_busy(True)
        app.v['emulator.active'].set('mame')
        self.assertEqual(app.emulator(), 'megadrive')
        self.assertEqual(self.local_names(), ['a.bin'])

    def test_browse_updates_only_the_chosen_setting(self):
        other = self.touch('elsewhere', 'a.md')
        app = self.make_app('emulator.active=megadrive\n')
        with mock.patch.object(rs.filedialog, 'askdirectory', return_value=str(other)):
            app.browse_source('snes.rom.source')
            self.assertEqual(app.v['megadrive.rom.source'].get(), 'roms_md/')
            self.assertEqual(self.local_names(), [])
            app.browse_source('megadrive.rom.source')
        self.assertEqual(app.v['megadrive.rom.source'].get(), 'elsewhere')
        self.assertEqual(self.local_names(), ['a.md'])
        self.assertEqual(app.v['snes.rom.source'].get(), 'elsewhere')


class ConfigurationPersistenceTests(AppCase):
    def saved(self):
        return rs.parse_properties(rs.CONFIG.read_text(encoding='utf-8'))

    def test_save_writes_every_key_and_reload_restores_megadrive_selection(self):
        app = self.make_app('emulator.active=megadrive\n')
        app.v['megadrive.remote_dir'].set('/custom/md/')
        app.v['ssh.host'].set('ipad.invalid')
        app.save()
        saved = self.saved()
        self.assertEqual(set(saved), set(rs.DEFAULTS))
        self.assertEqual((saved['emulator.active'], saved['megadrive.remote_dir']), ('megadrive', '/custom/md/'))
        reloaded = rs.App(self.root)
        self.assertEqual((reloaded.emulator(), reloaded.v['megadrive.remote_dir'].get(), reloaded.v['ssh.host'].get()),
                         ('megadrive', '/custom/md/', 'ipad.invalid'))

    def test_saving_from_megadrive_preserves_hidden_mame_and_snes_values(self):
        app = self.make_app('rom.source=roms_mame/\nssh.remote_dir=/mame/remote/\nsamples.remote_dir=/mame/samples/\n'
                            'snes.remote_dir=/snes/remote/\nemulator.active=megadrive\n')
        app.save()
        saved = self.saved()
        self.assertEqual((saved['ssh.remote_dir'], saved['samples.remote_dir'], saved['snes.remote_dir']),
                         ('/mame/remote/', '/mame/samples/', '/snes/remote/'))
        self.assertEqual(saved['content.mode'], 'roms')

    def test_legacy_config_opens_as_mame_with_megadrive_defaults(self):
        legacy = ('rom.source=old_roms/\nssh.host=10.0.0.9\nssh.remote_dir=/legacy/\nsamples.source=old_samples/\n')
        app = self.make_app(legacy)
        self.assertEqual((app.emulator(), app.v['rom.source'].get(), app.v['ssh.remote_dir'].get()),
                         ('mame', 'old_roms/', '/legacy/'))
        self.assertEqual((app.v['megadrive.rom.source'].get(), app.v['megadrive.remote_dir'].get()),
                         ('roms_md/', '/var/mobile/Media/ROMs/MD.emu/roms/'))
        app.save()
        self.assertEqual(self.saved()['rom.source'], 'old_roms/')

    def test_credentials_are_blanked_unless_user_confirms_plain_text_saving(self):
        app = self.make_app()
        app.v['ssh.password'].set('secret')
        app.v['ssh.key_passphrase'].set('phrase')
        app.save()
        self.assertEqual((self.saved()['ssh.password'], self.saved()['ssh.key_passphrase']), ('', ''))
        app.v['ssh.save_credentials'].set('true')
        self.dialogs['askyesno'].return_value = False
        rs.CONFIG.unlink()
        app.save()
        self.assertFalse(rs.CONFIG.exists())
        self.dialogs['askyesno'].return_value = True
        app.save()
        self.assertEqual(self.saved()['ssh.password'], 'secret')

    def test_save_rejects_invalid_values_without_writing(self):
        app = self.make_app()
        app.v['ssh.host'].set('bad\nhost')
        app.save()
        self.assertFalse(rs.CONFIG.exists())
        self.dialogs['showerror'].assert_called_once()

    def test_values_validation_for_megadrive(self):
        app = self.make_app('emulator.active=megadrive\n')
        self.fill_connection()
        values = app.values()
        self.assertEqual((values['operation.emulator'], values['operation.source'], values['operation.remote_dir']),
                         ('megadrive', 'roms_md/', '/var/mobile/Media/ROMs/MD.emu/roms/'))
        cases = (('megadrive.remote_dir', 'relative/dir', 'absolute remote'), ('ssh.port', '70000', 'Invalid SSH port'),
                 ('ssh.port', 'abc', None), ('ssh.username', '', 'host and username'),
                 ('megadrive.rom.source', 'missing_dir/', 'source directory'),
                 ('ssh.host', 'a\0b', 'line breaks'), ('ssh.auth_mode', 'key', 'private key'))
        for key, bad, message in cases:
            original = app.v[key].get()
            app.v[key].set(bad)
            with self.assertRaises(ValueError) as caught:
                app.values()
            if message:
                self.assertIn(message, str(caught.exception))
            app.v[key].set(original)
        self.assertEqual(app.values()['operation.emulator'], 'megadrive')

    def test_remote_directory_is_validated_for_the_active_profile_only(self):
        app = self.make_app('emulator.active=megadrive\n')
        self.fill_connection()
        app.v['snes.remote_dir'].set('relative')
        app.v['ssh.remote_dir'].set('relative')
        self.assertEqual(app.values()['operation.remote_dir'], '/var/mobile/Media/ROMs/MD.emu/roms/')
        self.select('snes')
        with self.assertRaises(ValueError):
            app.values()


class OperationConfirmationTests(AppCase):
    def setUp(self):
        super().setUp()
        self.reports = []
        thread = mock.patch.object(rs.threading, 'Thread')
        self.thread = thread.start()
        self.addCleanup(thread.stop)

    def capture(self, app, accept):
        def report(title, text, action=None):
            self.reports.append((title, text, action, app.busy))
            return accept
        app.report = report

    def prepare(self, emulator, folder, *names):
        self.touch(folder, *names)
        app = self.make_app(f'emulator.active={emulator}\n')
        self.fill_connection()
        self.capture(app, False)
        return app

    def test_copy_confirmation_shows_profile_destination_files_and_no_mame_warning(self):
        app = self.prepare('megadrive', 'roms_md', 'b.md', 'a.bin', 'c.srm')
        app.select_all()
        app.copy()
        title, text, action, was_busy = self.reports[0]
        self.assertEqual((title, action, was_busy), ('Confirm batch operation', 'Copy', True))
        for expected in ('Profile: Sega Mega Drive / Genesis ROMs', 'Copy 2 files', 'mobile@ipad.invalid', 'Port: 2222',
                         'Directory: /var/mobile/Media/ROMs/MD.emu/roms/'):
            self.assertIn(expected, text)
        self.assertLess(text.index('a.bin'), text.index('b.md'))
        self.assertNotIn('c.srm', text)
        self.assertNotIn('BIOS', text)
        self.assertFalse(app.busy)
        self.thread.assert_not_called()

    def test_accepted_copy_starts_worker_with_captured_values_and_files(self):
        app = self.prepare('megadrive', 'roms_md', 'a.bin')
        self.capture(app, True)
        app.select_all()
        app.copy()
        self.assertTrue(app.busy)
        _, kwargs = self.thread.call_args
        files, values, deleting = kwargs['args']
        self.assertEqual(([p.name for p in files], deleting), (['a.bin'], False))
        self.assertEqual((values['operation.emulator'], values['operation.remote_dir']),
                         ('megadrive', '/var/mobile/Media/ROMs/MD.emu/roms/'))
        self.select('mame')
        self.assertEqual(values['operation.emulator'], 'megadrive')
        self.thread.return_value.start.assert_called_once()

    def test_copy_errors_do_not_start_anything(self):
        app = self.prepare('megadrive', 'roms_md', 'a.bin')
        app.select_all()
        app.v['megadrive.rom.source'].set('roms_snes/')
        app.copy()
        self.assertIn('Source changed', self.dialogs['showerror'].call_args[0][1])
        app.v['megadrive.rom.source'].set('roms_md/')
        (self.base / 'roms_md' / 'a.bin').unlink()
        app.copy()
        self.assertIn('missing', self.dialogs['showerror'].call_args[0][1])
        app.marks.clear()
        app.copy()
        self.assertEqual((self.reports, self.thread.call_count), ([], 0))

    def listed(self, app, *names):
        app.remote, app.remote_target = list(names), app.signature()
        app.remote_marks.update(names)

    def test_delete_confirmation_has_mame_warning_only_for_mame(self):
        mame = self.prepare('mame', 'roms_mame')
        self.listed(mame, 'parent.zip')
        mame.delete()
        self.assertIn('BIOS and parent ZIPs', self.reports[-1][1])
        self.assertIn('Profile: MAME ROMs', self.reports[-1][1])
        self.select('megadrive')
        app = self.app
        self.listed(app, 'Sonic.BIN', 'x.zip')
        app.delete()
        text = self.reports[-1][1]
        self.assertIn('Delete permanently 2 files', text)
        self.assertIn('Profile: Sega Mega Drive / Genesis ROMs', text)
        self.assertNotIn('BIOS', text)
        self.assertEqual(self.reports[-1][2], 'Delete permanently')
        self.thread.assert_not_called()

    def test_delete_rejects_stale_unsafe_and_wrong_profile_names(self):
        app = self.prepare('megadrive', 'roms_md')
        self.listed(app, 'Sonic.srm')
        app.delete()
        self.assertIn('Unsafe filename', self.dialogs['showerror'].call_args[0][1])
        app.remote_marks.clear()
        self.listed(app, 'a/b.bin')
        app.remote.append('a/b.bin')
        app.delete()
        self.assertIn('Unsafe filename', self.dialogs['showerror'].call_args[0][1])
        app.remote_marks = {'ghost.bin'}
        app.delete()
        self.assertIn('Stale remote selection', self.dialogs['showerror'].call_args[0][1])
        app.remote_marks = {'a.bin'}
        app.remote, app.remote_target = ['a.bin'], ('mame', 'roms', 'other')
        app.delete()
        self.assertIn('Remote target changed', self.dialogs['showerror'].call_args[0][1])
        self.assertEqual((self.reports, self.thread.call_count), ([], 0))

    def test_declined_or_failed_confirmation_restores_idle_state(self):
        app = self.prepare('megadrive', 'roms_md', 'a.bin')
        app.select_all()
        app.report = mock.Mock(side_effect=RuntimeError('window failed'))
        with self.assertRaises(RuntimeError):
            app.copy()
        self.assertFalse(app.busy)

    def test_nothing_happens_when_busy_or_nothing_selected(self):
        app = self.prepare('megadrive', 'roms_md', 'a.bin')
        app.copy()
        app.delete()
        app.select_all()
        app.set_busy(True)
        app.copy()
        self.assertEqual((self.reports, self.thread.call_count), ([], 0))


class RefreshAndEventTests(AppCase):
    def setUp(self):
        super().setUp()
        thread = mock.patch.object(rs.threading, 'Thread')
        self.thread = thread.start()
        self.addCleanup(thread.stop)

    def test_automatic_refresh_without_password_does_not_connect(self):
        app = self.make_app('emulator.active=megadrive\n')
        app.refresh(automatic=True)
        self.assertIn('Enter the SSH password', app.status.get())
        self.assertEqual((self.thread.call_count, app.busy), (0, False))
        self.dialogs['showerror'].assert_not_called()

    def test_manual_refresh_with_invalid_settings_reports_error(self):
        app = self.make_app('emulator.active=megadrive\n')
        app.v['megadrive.remote_dir'].set('relative')
        app.refresh()
        self.assertEqual(self.thread.call_count, 0)
        self.dialogs['showerror'].assert_called_once()

    def test_refresh_captures_profile_destination_and_target(self):
        app = self.make_app('emulator.active=megadrive\n')
        self.fill_connection()
        app.refresh()
        _, kwargs = self.thread.call_args
        values, target, generation, automatic = kwargs['args']
        self.assertEqual((values['operation.emulator'], target, generation, automatic),
                         ('megadrive', app.signature(), app.generation, False))
        self.assertTrue(app.busy)

    def test_listing_from_another_profile_is_discarded(self):
        app = self.make_app('emulator.active=megadrive\n')
        stale_target, stale_generation = app.signature(), app.generation
        self.select('snes')
        app.events.put(('listed', ['a.bin'], stale_target, stale_generation, None))
        self.root.update()
        self.root.after(0)
        app.poll()
        self.assertEqual((app.remote, app.remote_target), ([], None))
        self.assertIn('discarded', app.status.get())

    def test_current_listing_is_applied_and_completed_deletion_updates_state(self):
        app = self.make_app('emulator.active=megadrive\n')
        app.events.put(('listed', ['a.bin', 'b.md'], app.signature(), app.generation, (512, 1024)))
        app.poll()
        self.assertEqual((app.remote, app.status.get()), (['a.bin', 'b.md'], 'Remote list refreshed.'))
        self.assertIn('50% free', app.space.get())
        app.remote_marks.add('a.bin')
        app.events.put(('completed', 'a.bin', True))
        app.poll()
        self.assertEqual((app.remote, app.remote_marks), (['b.md'], set()))

    def test_listing_error_clears_state_and_reports_for_manual_refresh(self):
        app = self.make_app('emulator.active=megadrive\n')
        app.remote, app.remote_target = ['a.bin'], app.signature()
        app.events.put(('list_error', 'OSError: boom', app.generation, False))
        app.poll()
        self.assertEqual((app.remote, app.remote_target), ([], None))
        self.assertEqual(self.dialogs['showerror'].call_args[0], ('Remote listing', 'OSError: boom'))

    def test_batch_result_summary_and_marks(self):
        self.touch('roms_md', 'a.bin', 'b.bin', 'c.bin')
        app = self.make_app('emulator.active=megadrive\n')
        app.select_all()
        files = sorted(app.marks, key=lambda p: p.name)
        reports = []
        app.report = lambda title, text, action=None: reports.append((title, text))
        app.set_busy(True)
        app.events.put(('done', {'completed': [files[0]], 'failed': [(files[1], 'OSError: denied')], 'fatal': '',
                                 'pending': [files[2]], 'deleting': False}))
        app.poll()
        self.assertFalse(app.busy)
        self.assertEqual(app.status.get(), 'Completed: 1 | Failed: 1 | Pending: 1')
        self.assertEqual({p.name for p in app.marks}, {'b.bin', 'c.bin'})
        self.assertIn('FAILED: b.bin — OSError: denied', reports[0][1])
        self.assertIn('PENDING: c.bin', reports[0][1])


if __name__ == '__main__':
    unittest.main()
