import unittest
from unittest import mock

from support import AppCase, rs


class PresenceTests(AppCase):
    def badges(self):
        return {path.name: self.app.cards[path][3].cget('text') for path in self.app.cards}

    def load_remote(self, names):
        self.app.events.put(('listed', list(names), self.app.signature(), self.app.generation, None))
        self.app.poll()

    def test_unknown_before_listing_shows_no_presence_and_global_unchecked_state(self):
        self.touch('roms_md', 'a.bin', 'b.bin')
        app = self.make_app('emulator.active=megadrive\n')
        self.assertEqual(set(self.badges().values()), {''})
        self.assertIn('not checked', app.presence.get())
        self.assertFalse(app.marks)

    def test_present_and_absent_by_exact_case_sensitive_full_name(self):
        self.touch('roms_md', 'a.bin', 'B.bin', 'c.bin', 'd.md')
        app = self.make_app('emulator.active=megadrive\n')
        self.load_remote(['a.bin', 'b.bin', 'd.bin', 'c'])
        self.assertEqual(self.badges(), {'a.bin': rs.PRESENT_LABEL, 'B.bin': '', 'c.bin': '', 'd.md': ''})
        self.assertNotIn('not checked', app.presence.get())
        self.assertIn('not a content check'.lower(), app.presence.get().lower())

    def test_presence_does_not_change_selection_and_present_files_can_be_copied(self):
        self.touch('roms_md', 'a.bin', 'b.bin')
        app = self.make_app('emulator.active=megadrive\n')
        self.load_remote(['a.bin'])
        self.assertEqual(app.marks, set())
        path = next(p for p in app.roms if p.name == 'a.bin')
        app.toggle(path)
        self.assertEqual(app.marks, {path})
        self.assertEqual(self.badges()['a.bin'], rs.PRESENT_LABEL)
        app.toggle(path)
        self.assertEqual(app.marks, set())
        app.select_all()
        self.assertEqual(len(app.marks), 2)
        self.assertEqual(str(app.copy_button.cget('state')), 'normal')
        self.fill_connection()
        with mock.patch.object(rs.threading, 'Thread') as thread, \
                mock.patch.object(app, 'report', return_value=True) as report:
            app.copy()
        self.assertEqual(report.call_args[0][0], 'Confirm batch operation')
        self.assertIn('Existing remote files may be overwritten.', report.call_args[0][1])
        thread.assert_called_once()

    def test_remote_search_filter_does_not_affect_presence(self):
        self.touch('roms_md', 'a.bin', 'b.bin')
        app = self.make_app('emulator.active=megadrive\n')
        self.load_remote(['a.bin', 'b.bin'])
        app.remote_search.set('zzz')
        self.assertEqual(list(app.remote_rows.values()), [])
        self.assertEqual(set(self.badges().values()), {rs.PRESENT_LABEL})

    def test_local_search_and_pagination_keep_indicators(self):
        names = [f'g{i:03}.bin' for i in range(rs.PAGE_SIZE + 5)]
        self.touch('roms_md', *names)
        app = self.make_app('emulator.active=megadrive\n')
        remote = [names[0], names[-1]]
        self.load_remote(remote)
        self.assertEqual(self.badges()[names[0]], rs.PRESENT_LABEL)
        app.turn(1)
        self.assertEqual(self.badges()[names[-1]], rs.PRESENT_LABEL)
        app.search.set('g04')
        app.filter()
        self.assertEqual(self.badges()[names[-1]], rs.PRESENT_LABEL)
        app.load()
        self.assertEqual(self.badges()[names[-1]], rs.PRESENT_LABEL)

    def test_mame_roms_samples_and_snes_use_full_name_with_extension(self):
        self.touch('roms_mame', 'pacman.zip')
        self.touch('samples_mame', 'pacman.zip', 'dkong.zip')
        self.touch('roms_snes', 'game.sfc')
        app = self.make_app()
        self.load_remote(['pacman.zip'])
        self.assertEqual(self.badges(), {'pacman.zip': rs.PRESENT_LABEL})
        self.select('mame', 'samples')
        self.assertEqual(set(self.badges().values()), {''})
        self.load_remote(['dkong.zip'])
        self.assertEqual(self.badges(), {'dkong.zip': rs.PRESENT_LABEL, 'pacman.zip': ''})
        self.select('snes')
        self.load_remote(['game', 'game.sfc'])
        self.assertEqual(self.badges(), {'game.sfc': rs.PRESENT_LABEL})

    def test_invalidation_by_connection_directory_listing_mode_and_profile(self):
        self.touch('roms_md', 'a.bin')
        self.touch('roms_snes', 'a.sfc')
        app = self.make_app('emulator.active=megadrive\n')
        for key, value in (('ssh.host', 'other.invalid'), ('ssh.port', '2223'), ('ssh.username', 'x'),
                           ('megadrive.remote_dir', '/other/'), ('ssh.remote_listing_mode', 'sftp')):
            self.load_remote(['a.bin'])
            self.assertEqual(self.badges(), {'a.bin': rs.PRESENT_LABEL}, key)
            app.v[key].set(value)
            self.assertEqual(self.badges(), {'a.bin': ''}, key)
            self.assertIn('not checked', app.presence.get(), key)
        self.load_remote(['a.bin', 'a.sfc'])
        self.select('snes')
        self.assertEqual(self.badges(), {'a.sfc': ''})
        self.select('megadrive')
        self.assertEqual(self.badges(), {'a.bin': ''})

    def test_profiles_do_not_share_remote_presence(self):
        self.touch('roms_md', 'a.bin')
        self.touch('roms_snes', 'a.sfc')
        app = self.make_app('emulator.active=megadrive\n')
        self.load_remote(['a.bin', 'a.sfc'])
        self.select('snes')
        self.assertEqual(app.remote, [])
        self.assertEqual(self.badges(), {'a.sfc': ''})

    def test_stale_results_are_rejected(self):
        self.touch('roms_md', 'a.bin')
        app = self.make_app('emulator.active=megadrive\n')
        target, generation = app.signature(), app.generation
        app.v['ssh.host'].set('other.invalid')
        app.events.put(('listed', ['a.bin'], target, generation, None))
        app.poll()
        self.assertEqual(self.badges(), {'a.bin': ''})
        self.assertIn('not checked', app.presence.get())

    def test_listing_error_removes_indicator(self):
        self.touch('roms_md', 'a.bin')
        app = self.make_app('emulator.active=megadrive\n')
        self.load_remote(['a.bin'])
        app.events.put(('list_error', 'OSError: boom', app.generation, True))
        app.poll()
        self.assertEqual(self.badges(), {'a.bin': ''})

    def test_refresh_after_copy_and_delete_updates_indicators(self):
        self.touch('roms_md', 'a.bin', 'b.bin')
        app = self.make_app('emulator.active=megadrive\n')
        self.load_remote(['a.bin'])
        app.set_busy(True)
        app.report = lambda *args, **kwargs: None
        scheduled = []
        with mock.patch.object(app.root, 'after', side_effect=lambda ms, fn=None, *a: scheduled.append(fn)):
            app.events.put(('done', {'completed': [next(p for p in app.roms if p.name == 'b.bin')], 'failed': [],
                                     'fatal': '', 'pending': [], 'deleting': False}))
            app.poll()
        self.assertIn(app.refresh, scheduled)
        self.load_remote(['a.bin', 'b.bin'])
        self.assertEqual(set(self.badges().values()), {rs.PRESENT_LABEL})
        app.events.put(('completed', 'a.bin', True))
        app.poll()
        self.assertEqual(self.badges(), {'a.bin': '', 'b.bin': rs.PRESENT_LABEL})

    def test_no_periodic_connections_are_started(self):
        self.touch('roms_md', 'a.bin')
        with mock.patch.object(rs.threading, 'Thread') as thread:
            app = self.make_app('emulator.active=megadrive\n')
            app.filter()
            app.render()
        thread.assert_not_called()


if __name__ == '__main__':
    unittest.main()
