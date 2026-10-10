import asyncio
import json
import shlex
import shutil
import stat
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from support import AppCase, rs

REMOTE_DIR = '/var/mobile/Media/ROMs/MD.emu/roms/'


class FakeConnection:
    """Stands in for an asyncssh connection; records commands and never touches a network."""

    def __init__(self, runner=None, sftp=None, closed=False):
        self.commands, self.runner, self.sftp, self.closed = [], runner, sftp, closed

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def is_closed(self):
        return self.closed

    async def run(self, command, check=False, timeout=None):
        self.commands.append(command)
        if self.runner:
            return self.runner(command)
        return SimpleNamespace(stdout='', exit_status=0)

    async def start_sftp_client(self):
        return self.sftp


class FakeSftp:
    def __init__(self, entries=None):
        self.entries, self.removed = entries or {}, []
        self.exited = False

    async def listdir(self, directory):
        return list(self.entries)

    async def stat(self, path):
        return self.entries[path.rsplit('/', 1)[1]]

    lstat = stat

    async def statvfs(self, directory):
        raise OSError('no statvfs')

    async def remove(self, path):
        self.removed.append(path)

    def exit(self):
        self.exited = True

    async def wait_closed(self):
        pass


def regular():
    return SimpleNamespace(permissions=stat.S_IFREG | 0o644, type=1)


def symlink():
    return SimpleNamespace(permissions=stat.S_IFLNK | 0o777, type=3)


def directory():
    return SimpleNamespace(permissions=stat.S_IFDIR | 0o755, type=2)


def real_shell(command):
    """Run the listing command with a real POSIX shell against a temporary directory (df is simulated)."""
    if command.startswith('df '):
        return SimpleNamespace(stdout='', exit_status=1)
    done = subprocess.run(['sh', '-c', command], capture_output=True, check=True)
    return SimpleNamespace(stdout=done.stdout.decode(), exit_status=0)


class TransferCase(AppCase):
    def prepare(self, emulator='megadrive', listing='ssh'):
        app = self.make_app(f'emulator.active={emulator}\nssh.remote_listing_mode={listing}\n')
        self.fill_connection()
        return app

    def run_async(self, coroutine):
        return asyncio.run(coroutine)


class ListingTests(TransferCase):
    @unittest.skipUnless(shutil.which('sh'), 'POSIX sh not available')
    def test_ssh_listing_runs_profile_filter_in_a_real_shell(self):
        remote = self.touch('remote', 'Sonic.BIN', 'a.Md', 'b.gen', 'c.SMD', 'd.zip', 'e.srm', 'e.sav', 'e.sfc',
                            'f.cue', "it's here.bin", 'with space.md')
        (remote / 'dir.bin').mkdir()
        (remote / 'link.bin').symlink_to(remote / 'a.Md')
        expected = {'megadrive': ['a.Md', 'b.gen', 'c.SMD', "it's here.bin", 'link.bin', 'Sonic.BIN', 'd.zip',
                                  'with space.md'],
                    'mame': ['d.zip'], 'snes': ['d.zip', 'e.sfc']}
        for emulator, names in expected.items():
            app = self.prepare(emulator)
            self.select(emulator)
            app.v[rs.active_keys('roms', emulator)[1]].set(str(remote) + '/')
            values = app.values()
            connection = FakeConnection(runner=real_shell)
            app.connect = mock.AsyncMock(return_value=connection)
            listed, space = self.run_async(app.list_async(values))
            self.assertEqual(sorted(listed, key=str.casefold), sorted(names, key=str.casefold), emulator)
            self.assertIsNone(space)

    @unittest.skipUnless(shutil.which('sh'), 'POSIX sh not available')
    def test_ssh_listing_reports_missing_directory(self):
        app = self.prepare()
        app.v['megadrive.remote_dir'].set(str(self.base / 'nope') + '/')
        app.connect = mock.AsyncMock(return_value=FakeConnection(runner=real_shell))
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_async(app.list_async(app.values()))

    def test_sftp_listing_filters_by_extension_and_regular_files(self):
        sftp = FakeSftp({'a.bin': regular(), 'b.MD': regular(), 'c.srm': regular(), 'd.gen': directory(),
                         'e.smd': symlink(), 'f.zip': regular()})
        app = self.prepare(listing='sftp')
        connection = FakeConnection(sftp=sftp, runner=lambda c: SimpleNamespace(stdout='', exit_status=1))

        class Client:
            async def __aenter__(self_inner):
                return sftp

            async def __aexit__(self_inner, *exc):
                return False
        connection.start_sftp_client = lambda: Client()
        app.connect = mock.AsyncMock(return_value=connection)
        names, space = self.run_async(app.list_async(app.values()))
        self.assertEqual(names, ['a.bin', 'b.MD', 'f.zip'])
        self.assertIsNone(space)

    def test_regular_file_detection(self):
        self.assertTrue(rs.App.regular(regular()))
        self.assertTrue(rs.App.regular(SimpleNamespace(permissions=None, type=1)))
        self.assertFalse(rs.App.regular(symlink()))
        self.assertFalse(rs.App.regular(SimpleNamespace(permissions=None, type=2)))

    def test_list_worker_posts_result_or_error_event(self):
        app = self.prepare()
        values = app.values()
        app.list_async = mock.AsyncMock(return_value=(['a.bin'], (1, 2)))
        app.list_worker(values, 'target', 7)
        self.assertEqual(app.events.get_nowait(), ('listed', ['a.bin'], 'target', 7, (1, 2)))
        app.list_async = mock.AsyncMock(side_effect=OSError('down'))
        app.list_worker(values, 'target', 7, automatic=True)
        self.assertEqual(app.events.get_nowait(), ('list_error', 'OSError: down', 7, True))


class BatchTests(TransferCase):
    def events(self, app):
        found = []
        while not app.events.empty():
            found.append(app.events.get_nowait())
        return found

    def test_copy_sends_each_file_to_the_profile_directory_and_continues_after_a_file_error(self):
        folder = self.touch('roms_md', 'a.bin', 'b.md', 'c.gen')
        app = self.prepare()
        connection = FakeConnection()
        app.connect = mock.AsyncMock(return_value=connection)
        sent = []

        async def scp(source, destination, progress_handler=None):
            if source.name == 'b.md':
                raise OSError('disk full')
            sent.append((source, destination))
            progress_handler(source, destination, 4, 4)
        files = tuple(sorted(folder.iterdir()))
        values = dict(app.values())
        result = {'completed': [], 'failed': [], 'fatal': '', 'deleting': False}
        with mock.patch.object(rs.asyncssh, 'scp', scp):
            self.run_async(app.batch_async(files, values, False, result))
        self.assertEqual([(p.name, d) for p, d in sent],
                         [('a.bin', (connection, REMOTE_DIR)), ('c.gen', (connection, REMOTE_DIR))])
        self.assertEqual([p.name for p in result['completed']], ['a.bin', 'c.gen'])
        self.assertEqual([(p.name, e) for p, e in result['failed']], [('b.md', 'OSError: disk full')])
        kinds = [event[0] for event in self.events(app)]
        self.assertIn('progress', kinds)
        self.assertEqual(kinds.count('completed'), 2)

    def test_copy_stops_when_the_connection_is_lost(self):
        folder = self.touch('roms_md', 'a.bin', 'b.md')
        app = self.prepare()
        connection = FakeConnection(closed=True)
        app.connect = mock.AsyncMock(return_value=connection)
        scp = mock.AsyncMock(side_effect=OSError('reset'))
        files, result = tuple(sorted(folder.iterdir())), {'completed': [], 'failed': [], 'fatal': '', 'deleting': False}
        with mock.patch.object(rs.asyncssh, 'scp', scp), self.assertRaises(OSError):
            self.run_async(app.batch_async(files, dict(app.values()), False, result))
        self.assertEqual(scp.await_count, 1)

    def test_batch_worker_reports_pending_files_after_a_fatal_error(self):
        folder = self.touch('roms_md', 'a.bin', 'b.md')
        app = self.prepare()
        files = tuple(sorted(folder.iterdir()))

        async def fake(files, values, deleting, result):
            result['completed'].append(files[0])
            raise ConnectionError('lost')
        app.batch_async = fake
        app.batch_worker(files, dict(app.values()), False)
        kind, result = app.events.get_nowait()
        self.assertEqual(kind, 'done')
        self.assertEqual(([p.name for p in result['completed']], [p.name for p in result['pending']]),
                         (['a.bin'], ['b.md']))
        self.assertEqual(result['fatal'], 'ConnectionError: lost')

    def test_ssh_delete_quotes_names_and_stays_inside_the_profile_directory(self):
        app = self.prepare()
        connection = FakeConnection()
        app.connect = mock.AsyncMock(return_value=connection)
        names = ('Sonic.BIN', "it's; rm -rf x.md")
        result = {'completed': [], 'failed': [], 'fatal': '', 'deleting': True}
        self.run_async(app.batch_async(names, dict(app.values()), True, result))
        self.assertEqual(result['completed'], list(names))
        for name, command in zip(names, connection.commands):
            self.assertIn(shlex.quote(REMOTE_DIR + name), command)
            self.assertIn('[ ! -L', command)
            self.assertTrue(command.rstrip().endswith('rm ' + shlex.quote(REMOTE_DIR + name)))

    def test_sftp_delete_removes_regular_files_and_rejects_symlinks_and_directories(self):
        sftp = FakeSftp({'a.bin': regular(), 'b.md': symlink(), 'c.gen': directory()})
        app = self.prepare(listing='sftp')
        app.connect = mock.AsyncMock(return_value=FakeConnection(sftp=sftp))
        result = {'completed': [], 'failed': [], 'fatal': '', 'deleting': True}
        self.run_async(app.batch_async(('a.bin', 'b.md', 'c.gen'), dict(app.values()), True, result))
        self.assertEqual(sftp.removed, [REMOTE_DIR + 'a.bin'])
        self.assertEqual(result['completed'], ['a.bin'])
        self.assertEqual([name for name, _ in result['failed']], ['b.md', 'c.gen'])
        self.assertTrue(all('Not a regular file' in error for _, error in result['failed']))
        self.assertTrue(sftp.exited)

    def test_remote_directory_without_trailing_slash_is_normalised_for_copy(self):
        folder = self.touch('roms_md', 'a.bin')
        app = self.prepare()
        app.v['megadrive.remote_dir'].set('/custom/md')
        connection = FakeConnection()
        app.connect = mock.AsyncMock(return_value=connection)
        scp = mock.AsyncMock()
        result = {'completed': [], 'failed': [], 'fatal': '', 'deleting': False}
        with mock.patch.object(rs.asyncssh, 'scp', scp):
            self.run_async(app.batch_async((folder / 'a.bin',), dict(app.values()), False, result))
        self.assertEqual(scp.await_args.args[1], (connection, '/custom/md/'))


class FakeKey:
    def __init__(self, public=b'ssh-rsa AAAA', fingerprint='SHA256:fake'):
        self.public, self.fingerprint = public, fingerprint

    def export_public_key(self, form):
        return self.public

    def get_fingerprint(self):
        return self.fingerprint


class ConnectTests(TransferCase):
    def setUp(self):
        super().setUp()
        self.key = FakeKey()
        self.get_key = mock.patch.object(rs.asyncssh, 'get_server_host_key', mock.AsyncMock(return_value=self.key))
        self.connect = mock.patch.object(rs.asyncssh, 'connect', mock.AsyncMock(return_value='connection'))
        self.get_key.start(), self.connect.start()
        self.addCleanup(self.get_key.stop)
        self.addCleanup(self.connect.stop)

    def test_known_matching_key_connects_with_password_and_no_agent(self):
        app = self.prepare()
        rs.HOSTS.write_text(json.dumps({'[ipad.invalid]:2222': 'ssh-rsa AAAA'}), encoding='utf-8')
        self.assertEqual(self.run_async(app.connect(app.values())), 'connection')
        options = rs.asyncssh.connect.await_args.kwargs
        self.assertEqual((options['host'], options['port'], options['username'], options['client_keys']),
                         ('ipad.invalid', 2222, 'mobile', []))
        self.assertEqual((options['known_hosts'], options['agent_path'], options['preferred_auth']),
                         (([self.key], [], []), None, 'password,keyboard-interactive'))

    def test_changed_key_is_rejected_before_authenticating(self):
        app = self.prepare()
        rs.HOSTS.write_text(json.dumps({'[ipad.invalid]:2222': 'ssh-rsa DIFFERENT'}), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'Server key changed'):
            self.run_async(app.connect(app.values()))
        rs.asyncssh.connect.assert_not_awaited()

    def test_unknown_key_is_stored_only_after_approval(self):
        app = self.prepare()
        app.approve = mock.Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            self.run_async(app.connect(app.values()))
        self.assertFalse(rs.HOSTS.exists())
        app.approve = mock.Mock(return_value=True)
        self.run_async(app.connect(app.values()))
        self.assertEqual(json.loads(rs.HOSTS.read_text(encoding='utf-8')), {'[ipad.invalid]:2222': 'ssh-rsa AAAA'})

    def test_key_authentication_uses_configured_key_and_legacy_rsa_flag(self):
        app = self.prepare()
        key = self.base / 'id_test'
        key.write_text('not a real key', encoding='utf-8')
        app.v['ssh.auth_mode'].set('key')
        app.v['ssh.private_key'].set('id_test')
        app.v['ssh.legacy_rsa'].set('false')
        rs.HOSTS.write_text(json.dumps({'[ipad.invalid]:2222': 'ssh-rsa AAAA'}), encoding='utf-8')
        self.run_async(app.connect(app.values()))
        options = rs.asyncssh.connect.await_args.kwargs
        self.assertEqual((options['client_keys'], options['preferred_auth'], options['server_host_key_algs']),
                         ([str(key)], 'publickey', '-ssh-rsa'))


if __name__ == '__main__':
    unittest.main()
