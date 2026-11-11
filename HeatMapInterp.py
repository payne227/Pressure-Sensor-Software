"""PC heatmap for four sensors. Run 1ADC4Chan_Test.py as main.py on the Pico.

USB format: Results: [AIN0, AIN1, AIN2, AIN3], one complete scan per line.
Grid: AIN0/AIN1 on the top row, AIN2/AIN3 on the bottom row.
Legacy CH0: through CH3: scans are also accepted in that order.
Positive ADC counts are scaled to 0..65536; negative counts display as zero.
The original signed ADC counts remain visible for troubleshooting.

Install PC dependencies: python -m pip install numpy matplotlib pyserial
Close Thonny's serial connection before connecting here.
"""

import json
import tkinter as tk
from tkinter import ttk
from time import monotonic

import numpy as np
import serial
from serial.tools import list_ports
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class ForceMapApp:
    ROWS = 2
    COLS = 2
    RAW_MIN = -(1 << 23)
    RAW_MAX = (1 << 23) - 1
    DISPLAY_MAX = 65536
    UPDATE_MS = 200

    def __init__(self, root):
        self.root = root
        self.root.title("Live 2×2 Sensor Heat Map — ADS1256")
        self.running = True
        self.pending_update = None
        self.connection = None
        self.receive_buffer = b""
        self.connected_at = None
        self.last_reading_at = None
        self.received_bytes = 0
        self.channel_scan = []

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(controls, text="Pico USB port:").pack(side=tk.LEFT)
        self.port = ttk.Combobox(controls, width=16, state="readonly")
        self.port.pack(side=tk.LEFT, padx=8)
        ttk.Button(controls, text="Refresh", command=self.refresh_ports).pack(side=tk.LEFT)
        self.connect_button = ttk.Button(
            controls, text="Connect", command=self.toggle_connection
        )
        self.connect_button.pack(side=tk.LEFT, padx=8)
        self.status = tk.StringVar(value="Select the Pico's port and click Connect.")
        ttk.Label(root, textvariable=self.status, wraplength=600).pack(padx=8)
        self.serial_preview = tk.StringVar(value="USB data: none received")
        ttk.Label(root, textvariable=self.serial_preview, wraplength=600).pack(padx=8)
        self.refresh_ports()

        figure = Figure(figsize=(7, 5), dpi=100)
        axes = figure.add_subplot(111)

        # Keep the color scale fixed so colors remain comparable over time.
        self.heatmap = axes.imshow(
            np.full((self.ROWS, self.COLS), np.nan),
            cmap="inferno",
            vmin=0,
            vmax=self.DISPLAY_MAX,
            interpolation="nearest",
            origin="upper",
        )

        axes.set(
            title="2×2 Sensor Readings — ADS1256",
            xticks=range(self.COLS),
            yticks=range(self.ROWS),
            xticklabels=range(1, self.COLS + 1),
            yticklabels=range(1, self.ROWS + 1),
        )
        self.reading_texts = [
            axes.text(
                ch % self.COLS, ch // self.COLS,
                "AIN{}\nWaiting for data".format(ch),
                ha="center", va="center", color="white",
                bbox=dict(facecolor="black", alpha=0.6, edgecolor="none"),
            )
            for ch in range(self.ROWS * self.COLS)
        ]

        figure.colorbar(
            self.heatmap, ax=axes, label="Sensor level (scaled 0–65536)",
            ticks=[0, 16384, 32768, 49152, 65536],
        )
        figure.tight_layout()

        self.canvas = FigureCanvasTkAgg(figure, master=root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.pause_button = tk.Button(
            root, text="Pause", command=self.toggle_running
        )
        self.pause_button.pack(pady=8)

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.update_heatmap()

    def refresh_ports(self):
        ports = [port.device for port in list_ports.comports()]
        self.port["values"] = ports
        if self.port.get() not in ports:
            self.port.set(ports[0] if ports else "")

    def disconnect(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.receive_buffer = b""
        self.channel_scan = []
        self.connected_at = None
        self.connect_button.config(text="Connect")

    def toggle_connection(self):
        if self.connection is not None:
            self.disconnect()
            self.status.set("Disconnected. Display holds the last reading.")
            return
        if not self.port.get():
            self.status.set("No port selected. Plug in the Pico and click Refresh.")
            return
        try:
            # Nonblocking reads keep the window responsive if no data arrives.
            self.connection = serial.Serial(self.port.get(), 115200, timeout=0)
        except (serial.SerialException, OSError) as error:
            self.status.set("Could not connect: {}. Close Thonny's connection.".format(error))
            return
        self.receive_buffer = b""
        self.channel_scan = []
        self.connected_at = monotonic()
        self.last_reading_at = None
        self.received_bytes = 0
        self.serial_preview.set("USB data: none received")
        self.connect_button.config(text="Disconnect")
        self.status.set("Connected to {}. Waiting for four-channel scans...".format(self.port.get()))

    @classmethod
    def scale_reading(cls, raw):
        """Unipolar display scale; preserve signed counts separately for diagnosis."""
        return round(max(0, min(raw, cls.RAW_MAX)) * cls.DISPLAY_MAX / cls.RAW_MAX)

    def read_sensors(self):
        """Return the newest complete four-channel scan, or None if none arrived."""
        if self.connection is None:
            return None
        chunk = self.connection.read(min(self.connection.in_waiting, 4096))
        if chunk:
            self.received_bytes += len(chunk)
            self.serial_preview.set(
                "Latest USB data: " + repr(chunk.decode("utf-8", errors="replace")[-200:])
            )
        self.receive_buffer += chunk
        lines = self.receive_buffer.split(b"\n")
        self.receive_buffer = lines.pop()
        if len(self.receive_buffer) > 4096:
            self.receive_buffer = b""
            self.channel_scan = []
        latest = None
        for line in lines:
            text = line.decode("utf-8", errors="replace").strip()
            if text.startswith("CH"):
                # Only publish consecutive CH0, CH1, CH2, CH3 from one scan.
                try:
                    label, number = text.split(":", 1)
                    ch = int(label[2:])
                    value = int(number.strip())
                except ValueError:
                    self.channel_scan = []
                    continue
                if ch == 0:
                    self.channel_scan = []
                if (
                    ch == len(self.channel_scan) and 0 <= ch < 4
                    and self.RAW_MIN <= value <= self.RAW_MAX
                ):
                    self.channel_scan.append(value)
                    if len(self.channel_scan) == 4:
                        latest = self.channel_scan
                        self.channel_scan = []
                else:
                    self.channel_scan = []
                continue
            self.channel_scan = []
            if not text.startswith("Results:"):
                continue
            try:
                values = json.loads(text.split(":", 1)[1])
            except ValueError:
                continue
            if (
                isinstance(values, list)
                and len(values) == self.ROWS * self.COLS
                and all(
                    type(value) is int and self.RAW_MIN <= value <= self.RAW_MAX
                    for value in values
                )
            ):
                latest = values
        return latest

    def update_heatmap(self):
        try:
            # Drain USB even while paused so Resume shows current data.
            readings = self.read_sensors()
        except (serial.SerialException, OSError) as error:
            self.disconnect()
            self.status.set("Serial connection lost: {}".format(error))
            readings = None
        if readings is not None:
            self.last_reading_at = monotonic()
            self.status.set(
                "Receiving live readings from {}{}".format(
                    self.connection.port, " (display paused)" if not self.running else ""
                )
            )
        elif self.connection is not None:
            last_activity = self.last_reading_at or self.connected_at
            if last_activity is not None and monotonic() - last_activity > 3:
                if self.last_reading_at is not None:
                    self.status.set("Readings stopped. Display holds the last value. Check the Pico script.")
                elif not self.received_bytes:
                    self.status.set(
                        "Port open, but the Pico is sending no data. Save 1ADC4Chan_Test.py as "
                        "main.py on the Pico, close Thonny, and restart the Pico."
                    )
                else:
                    self.status.set(
                        "USB data received, but no complete Results: or CH0–CH3 scan. Check Latest USB data "
                        "below for a MicroPython prompt or an error."
                    )
        if self.running and readings is not None:
            levels = [self.scale_reading(value) for value in readings]
            self.heatmap.set_data(np.asarray(levels).reshape(self.ROWS, self.COLS))
            for ch, (value, level) in enumerate(zip(readings, levels)):
                self.reading_texts[ch].set_text(
                    "AIN{}\nLevel: {}\nADC: {}".format(ch, level, value)
                )
            self.canvas.draw_idle()

        # Schedule the next refresh without blocking Tkinter's event loop.
        self.pending_update = self.root.after(
            self.UPDATE_MS, self.update_heatmap
        )

    def toggle_running(self):
        self.running = not self.running
        self.pause_button.config(text="Pause" if self.running else "Resume")

    def close(self):
        if self.pending_update is not None:
            self.root.after_cancel(self.pending_update)
        self.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ForceMapApp(root)
    root.mainloop()
