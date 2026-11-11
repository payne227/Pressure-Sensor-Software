"""PC checks without a connected Pico or a Tk window: py -3.12 -m unittest -v."""

import builtins
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from matplotlib.figure import Figure

from HeatMapInterp import ForceMapApp


class FakePort:
    port = "test USB"
    data = b""

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, size):
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk


class SensorPipelineTests(unittest.TestCase):
    def setUp(self):
        self.app = ForceMapApp.__new__(ForceMapApp)
        self.app.connection = FakePort()
        self.app.receive_buffer = b""
        self.app.channel_scan = []
        self.app.received_bytes = 0
        self.app.serial_preview = SimpleNamespace(set=lambda value: None)

    def receive(self, data):
        self.app.connection.data += data
        return self.app.read_sensors()

    def test_legacy_screenshot_format_and_fragmentation(self):
        self.assertIsNone(self.receive(b"CH0: -32769\r\nCH1: -327"))
        self.assertEqual(
            self.receive(b"69\r\nCH2: -32769\r\nCH3: -32769\r\n--------\r\n"),
            [-32769] * 4,
        )

    def test_incomplete_legacy_scans_are_not_mixed(self):
        self.assertIsNone(self.receive(b"CH0: 1\nCH2: 3\nCH3: 4\n"))
        self.assertIsNone(self.receive(b"CH0: 1\n---\nCH1: 2\nCH2: 3\nCH3: 4\n"))
        self.assertEqual(self.receive(b"CH0: 5\nCH1: 6\nCH2: 7\nCH3: 8\n"), [5, 6, 7, 8])

    def test_json_validation_and_newest_complete_scan(self):
        for invalid in (b"null", b"[1,2,3]", b"[1,2,3,true]", b"[1,2,3,4.0]",
                        b"[1,2,3,8388608]", b"invalid"):
            self.assertIsNone(self.receive(b"Results: " + invalid + b"\n"))
        self.assertIsNone(self.receive(b"Results: [1,2,"))
        self.assertEqual(self.receive(b"3,4]\nResults: [-8388608,0,8388607,5]\n"),
                         [-8388608, 0, 8388607, 5])

    def test_unipolar_scale(self):
        self.assertEqual([ForceMapApp.scale_reading(value) for value in
                          (-8388608, -32769, 0, 4194304, 8388607)],
                         [0, 0, 0, 32768, 65536])

    def test_grid_labels_and_pause(self):
        axes = Figure().add_subplot()
        self.app.heatmap = axes.imshow([[0, 0], [0, 0]])
        self.app.reading_texts = [axes.text(ch % 2, ch // 2, "") for ch in range(4)]
        self.app.canvas = SimpleNamespace(draw_idle=lambda: None)
        self.app.root = SimpleNamespace(after=lambda *args: "scheduled")
        self.app.status = SimpleNamespace(set=lambda value: None)
        self.app.running = True
        self.app.connection.data = b"Results: [0,4194304,8388607,-32769]\n"
        self.app.update_heatmap()
        self.assertEqual(self.app.heatmap.get_array().tolist(), [[0, 32768], [65536, 0]])
        self.assertEqual(self.app.reading_texts[3].get_text(), "AIN3\nLevel: 0\nADC: -32769")
        self.app.running = False
        self.app.connection.data = b"Results: [1,2,3,4]\n"
        self.app.update_heatmap()
        self.assertEqual(self.app.heatmap.get_array().tolist(), [[0, 32768], [65536, 0]])

    def test_firmware_setup_and_scan(self):
        class EndScan(Exception):
            pass

        class Pin:
            OUT, IN = 1, 0

            def __init__(self, number, mode=None, value=0):
                self.level = value

            def value(self, value=None):
                if value is not None:
                    self.level = value
                return self.level

        class SPI:
            MSB = 0

            def __init__(self, *args, **kwargs):
                self.settings = kwargs
                self.registers = {}
                self.mux_writes = []
                self.samples = iter((0, 4194304, 8388607, 0xFF7FFF))

            def write(self, data):
                self.command = data[0]
                if data[0] & 0xF0 == 0x50:
                    reg = data[0] & 0x0F
                    self.registers[reg] = data[2]
                    if reg == 1:
                        self.mux_writes.append(data[2])

            def read(self, size):
                if self.command & 0xF0 == 0x10:
                    return bytes([self.registers[self.command & 0x0F]])
                return next(self.samples).to_bytes(size, "big")

        def finish(seconds):
            raise EndScan

        def fake_import(name, *args, **kwargs):
            if name == "machine":
                return SimpleNamespace(Pin=Pin, SPI=SPI)
            if name == "time":
                return SimpleNamespace(sleep=finish, sleep_ms=lambda ms: None,
                                       sleep_us=lambda us: None, ticks_ms=lambda: 0,
                                       ticks_diff=lambda a, b: a - b)
            return builtins.__import__(name, *args, **kwargs)

        namespace = {"__builtins__": dict(vars(builtins), __import__=fake_import)}
        output = io.StringIO()
        firmware = Path(__file__).with_name("1ADC4Chan_Test.py").read_text(encoding="utf-8")
        with redirect_stdout(output), self.assertRaises(EndScan):
            exec(compile(firmware, "firmware", "exec"), namespace)
        self.assertEqual(namespace["spi"].settings["polarity"], 0)
        self.assertEqual(namespace["spi"].settings["phase"], 1)
        self.assertEqual(namespace["spi"].registers[2], 0)
        self.assertEqual(namespace["spi"].registers[3], 0xA1)
        self.assertEqual(namespace["spi"].mux_writes[-4:], [0x08, 0x18, 0x28, 0x38])
        self.assertEqual(self.receive(output.getvalue().encode()), [0, 4194304, 8388607, -32769])
        self.assertEqual(json.loads(output.getvalue().split(":", 1)[1]), namespace["results"])
        namespace["DRDY"].value(1)
        with self.assertRaisesRegex(OSError, "DRDY timeout"):
            namespace["wait_drdy"](timeout_ms=0)


if __name__ == "__main__":
    unittest.main()
