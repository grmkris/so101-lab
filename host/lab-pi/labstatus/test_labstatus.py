import contextlib
import ast
import importlib.util
import io
from pathlib import Path
import types
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name('labstatus.py')
SPEC = importlib.util.spec_from_file_location('labstatus', MODULE_PATH)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


class DashboardTests(unittest.TestCase):
    def make_touch(self, **kwargs):
        with patch.object(dashboard.Touch, 'connect'):
            return dashboard.Touch(**kwargs)

    def test_calibration_path_does_not_pin_device_number(self):
        document = '{"size":[320,480],"input_device":"/dev/input/event0","records":[{"raw":[0,0],"target":[0,0]},{"raw":[4095,0],"target":[319,0]},{"raw":[0,4095],"target":[0,479]}]}'
        with patch.object(Path, 'read_text', return_value=document):
            touch = self.make_touch(calibration='calibration.json')
        self.assertIsNotNone(touch.matrix)
        self.assertIsNone(touch.device)

    def test_discovery_uses_name_and_dynamic_event_number(self):
        touch = self.make_touch()
        paths = [Path('/sys/class/input/event0'), Path('/sys/class/input/event7')]

        def device_name(path, default=''):
            return 'ADS7846 Touchscreen' if 'event7' in str(path) else 'camera button'

        def ioctl(descriptor, request, buffer, mutate):
            buffer[:] = dashboard.struct.pack('iiiiii', 0, 0, 4095, 0, 0, 0)

        with patch.object(Path, 'glob', return_value=paths), patch.object(dashboard, 'read', side_effect=device_name), patch.object(dashboard.os, 'open', return_value=123) as opened, patch.object(dashboard.fcntl, 'ioctl', side_effect=ioctl):
            touch.connect()
        opened.assert_called_once_with('/dev/input/event7', dashboard.os.O_RDONLY | dashboard.os.O_NONBLOCK)
        self.assertEqual(touch.device, '/dev/input/event7')

    def test_missing_touch_reports_error(self):
        touch = self.make_touch()
        with patch.object(Path, 'glob', return_value=[]):
            with self.assertRaises(FileNotFoundError):
                touch.connect()

    def test_release_maps_to_tab_only_after_sync(self):
        touch = self.make_touch()
        for record in ((3, 0, 3100), (3, 1, 3500), (1, 330, 1), (1, 330, 0)):
            self.assertIsNone(touch.feed(*record))
        point = touch.feed(0, 0, 0)
        self.assertEqual(dashboard.tab_at(*point), 'Cameras')
        self.assertIsNone(touch.feed(0, 0, 0))

    def test_dropped_events_do_not_invent_tap(self):
        touch = self.make_touch()
        for record in ((3, 0, 3100), (3, 1, 3500), (1, 330, 1), (0, 3, 0), (1, 330, 0)):
            self.assertIsNone(touch.feed(*record))
        self.assertIsNone(touch.feed(0, 0, 0))

    def test_navigation_geometry(self):
        for point, expected in (((80, 405), 'Overview'), ((240, 405), 'Cameras'), ((80, 455), 'System'), ((240, 455), 'Session'), ((80, 379), None)):
            self.assertEqual(dashboard.tab_at(*point), expected)

    def test_collector_root_disk_ram_cpu_and_single_log(self):
        samples = iter(('cpu 10 0 10 80 0 0 0 0', 'cpu 20 0 20 160 0 0 0 0', 'cpu 30 0 30 240 0 0 0 0'))
        contents = {'/proc/meminfo': 'MemTotal: 2097152 kB\nMemAvailable: 1048576 kB', '/proc/uptime': '600.0 20.0', '/sys/class/thermal/thermal_zone0/temp': '51000'}

        def read_fixture(path, default=''):
            return next(samples) if path == '/proc/stat' else contents.get(path, default)

        collector = dashboard.Collector(debug=True)
        disk = types.SimpleNamespace(f_blocks=100, f_bfree=30, f_bavail=20, f_frsize=2**30)
        output = io.StringIO()
        with patch.object(dashboard, 'read', side_effect=read_fixture), patch.object(dashboard.PiStatsSampler, '_read', side_effect=read_fixture), patch.object(dashboard.PiStatsSampler, '_command', return_value='throttled=0x0'), patch.object(dashboard, 'command', return_value='0x0'), patch.object(dashboard.os, 'statvfs', return_value=disk) as disk_read, patch.object(dashboard.os, 'stat', return_value=types.SimpleNamespace(st_dev=1)), patch.object(dashboard.os, 'getloadavg', return_value=(.5, .4, .3)), contextlib.redirect_stdout(output):
            first = collector.sample()
            second = collector.sample()
            collector.sample()
        self.assertIsNone(first['cpu'])
        self.assertAlmostEqual(second['cpu'], 20)
        self.assertEqual(second['ram_used'], 1)
        self.assertEqual(second['ram_total'], 2)
        self.assertEqual(second['free'], 20)
        self.assertEqual(second['used'], 70)
        self.assertTrue(all(call.args == ('/',) for call in disk_read.call_args_list))
        self.assertEqual(output.getvalue().count('Stats sample:'), 1)

    def test_malformed_proc_stat_does_not_crash_or_update_cpu_baseline(self):
        sampler = dashboard.PiStatsSampler()
        with patch.object(sampler, '_read', return_value='cpu 10 bad 10'):
            self.assertIsNone(sampler._cpu_usage())
        self.assertIsNone(sampler._previous_cpu)

    def test_all_tabs_render_without_devices(self):
        for tab in dashboard.TABS:
            self.assertEqual(dashboard.draw(dashboard.demo(), tab).size, (320, 480))

    def test_hot_temperature_is_red(self):
        state = dashboard.demo()
        state['stats']['cpu_temp'] = 71
        image = dashboard.draw(state)
        self.assertTrue(((dashboard.np.asarray(image)[175:201, 12:150] == (255, 133, 142)).all(axis=2)).any())

    def test_throttle_ok_and_warnings(self):
        self.assertEqual(dashboard.throttle_status('0x0'), ('OK', dashboard.OK))
        self.assertEqual(dashboard.throttle_status('0x1')[1], dashboard.BAD)
        self.assertEqual(dashboard.throttle_status('0x10000')[1], dashboard.WARN)
        self.assertEqual(dashboard.throttle_status('unknown')[1], dashboard.WARN)

    def test_calibration_timeout_keeps_file_and_closes_handles(self):
        with patch.object(dashboard, 'Framebuffer') as framebuffer, patch.object(dashboard, 'Touch') as touch, patch.object(dashboard.time, 'monotonic', side_effect=(0, 46)), patch('builtins.open') as opened:
            with self.assertRaises(TimeoutError):
                dashboard.calibrate('calibration.json', '/dev/fb0')
        opened.assert_not_called()
        touch.return_value.close.assert_called_once()
        framebuffer.return_value.close.assert_called_once()

    def test_shared_stats_definitions_match_phone_module_snapshot(self):
        embedded = ast.parse(MODULE_PATH.read_text())
        shared = ast.parse(MODULE_PATH.with_name('pistats.py').read_text())
        names = {'PiStatsSampler', 'power_status', 'draw_stats'}
        embedded_nodes = {node.name: ast.dump(node) for node in embedded.body if getattr(node, 'name', None) in names}
        shared_nodes = {node.name: ast.dump(node) for node in shared.body if getattr(node, 'name', None) in names}
        self.assertEqual(embedded_nodes, shared_nodes)

    def test_calibration_success_replaces_json_atomically(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'calibration.json'
            path.write_text('old calibration')
            with patch.object(dashboard, 'Framebuffer'), patch.object(dashboard, 'Touch') as touch, patch.object(dashboard.time, 'monotonic', return_value=0), patch.object(dashboard.time, 'sleep'), patch.object(dashboard.os, 'replace', wraps=dashboard.os.replace) as replaced:
                touch.return_value.device = '/dev/input/event7'
                touch.return_value.poll.side_effect = [[(0, 0)], [(4095, 0)], [(4095, 4095)], [(0, 4095)]]
                dashboard.calibrate(str(path), '/dev/fb0')
            document = dashboard.json.loads(path.read_text())
            self.assertEqual(document['input_device'], '/dev/input/event7')
            self.assertEqual(len(document['records']), 4)
            self.assertEqual(list(Path(folder).iterdir()), [path])
            replaced.assert_called_once()

    def test_calibration_degenerate_taps_keep_existing_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'calibration.json'
            path.write_text('old calibration')
            with patch.object(dashboard, 'Framebuffer'), patch.object(dashboard, 'Touch') as touch, patch.object(dashboard.time, 'monotonic', return_value=0):
                touch.return_value.poll.return_value = [(10, 10)]
                with self.assertRaises(ValueError):
                    dashboard.calibrate(str(path), '/dev/fb0')
            self.assertEqual(path.read_text(), 'old calibration')


if __name__ == '__main__':
    unittest.main()
