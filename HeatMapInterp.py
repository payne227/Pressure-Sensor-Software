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

    # ---------------------------------------------------------
    # FINAL SENSOR ARRAY LAYOUT
    # 5 ROWS × 6 COLS = 30 SENSORS
    # ---------------------------------------------------------
    ROWS = 5
    COLS = 6
    SENSOR_COUNT = 30

    RAW_MIN = -(1 << 23)
    RAW_MAX = (1 << 23) - 1

    DISPLAY_MAX = 65536

    UPDATE_MS = 10

    def __init__(self, root):

        self.root = root
        self.root.title("Live 5×6 Pressure Sensor Heat Map")

        self.running = True
        self.pending_update = None

        self.connection = None
        self.receive_buffer = b""

        self.connected_at = None
        self.last_reading_at = None
        self.received_bytes = 0

        # ---------------------------------------------------------
        # CONTROLS
        # ---------------------------------------------------------
        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(
            controls,
            text="Pico USB Port:"
        ).pack(side=tk.LEFT)

        self.port = ttk.Combobox(
            controls,
            width=20,
            state="readonly"
        )
        self.port.pack(side=tk.LEFT, padx=8)

        ttk.Button(
            controls,
            text="Refresh",
            command=self.refresh_ports
        ).pack(side=tk.LEFT)

        self.connect_button = ttk.Button(
            controls,
            text="Connect",
            command=self.toggle_connection
        )

        self.connect_button.pack(
            side=tk.LEFT,
            padx=8
        )

        self.status = tk.StringVar(
            value="Select the Pico USB port and click Connect."
        )

        ttk.Label(
            root,
            textvariable=self.status,
            wraplength=1200
        ).pack(padx=8)

        self.serial_preview = tk.StringVar(
            value="USB data: none received"
        )

        ttk.Label(
            root,
            textvariable=self.serial_preview,
            wraplength=1200
        ).pack(padx=8)

        self.refresh_ports()

        # ---------------------------------------------------------
        # HEATMAP
        # ---------------------------------------------------------
        figure = Figure(
            figsize=(12, 8),
            dpi=100
        )

        axes = figure.add_subplot(111)

        self.heatmap = axes.imshow(
            np.zeros((self.ROWS, self.COLS)),
            cmap="inferno",
            vmin=0,
            vmax=self.DISPLAY_MAX,
            interpolation="nearest",
            origin="upper"
        )

        axes.set(
            title="5×6 Force Sensor Array",
            xticks=range(self.COLS),
            yticks=range(self.ROWS),
            xticklabels=[str(i + 1) for i in range(self.COLS)],
            yticklabels=[str(i + 1) for i in range(self.ROWS)]
        )

        axes.set_xlabel("Column")
        axes.set_ylabel("Row")

        self.reading_texts = []

        for sensor in range(self.SENSOR_COUNT):

            row = sensor // self.COLS
            col = sensor % self.COLS

            text = axes.text(
                col,
                row,
                f"S{sensor + 1}\nWaiting",
                ha="center",
                va="center",
                color="white",
                fontsize=8,
                bbox=dict(
                    facecolor="black",
                    alpha=0.6,
                    edgecolor="none"
                )
            )

            self.reading_texts.append(text)

        figure.colorbar(
            self.heatmap,
            ax=axes,
            label="Sensor Level (0–65536)",
            ticks=[
                0,
                16384,
                32768,
                49152,
                65536
            ]
        )

        figure.tight_layout()

        self.canvas = FigureCanvasTkAgg(
            figure,
            master=root
        )

        self.canvas.get_tk_widget().pack(
            fill=tk.BOTH,
            expand=True
        )

        # ---------------------------------------------------------
        # PAUSE BUTTON
        # ---------------------------------------------------------
        self.pause_button = tk.Button(
            root,
            text="Pause",
            command=self.toggle_running
        )

        self.pause_button.pack(pady=8)

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )

        self.update_heatmap()

    # ---------------------------------------------------------
    # SERIAL PORT DISCOVERY
    # ---------------------------------------------------------
    def refresh_ports(self):

        ports = [
            port.device
            for port in list_ports.comports()
        ]

        self.port["values"] = ports

        if self.port.get() not in ports:

            self.port.set(
                ports[0] if ports else ""
            )

    # ---------------------------------------------------------
    # DISCONNECT
    # ---------------------------------------------------------
    def disconnect(self):

        if self.connection is not None:

            self.connection.close()
            self.connection = None

        self.receive_buffer = b""

        self.connected_at = None
        self.last_reading_at = None

        self.connect_button.config(
            text="Connect"
        )

    # ---------------------------------------------------------
    # CONNECT / DISCONNECT
    # ---------------------------------------------------------
    def toggle_connection(self):

        if self.connection is not None:

            self.disconnect()

            self.status.set(
                "Disconnected. Display holds last reading."
            )

            return

        if not self.port.get():

            self.status.set(
                "No port selected. Plug in Pico and click Refresh."
            )

            return

        try:

            self.connection = serial.Serial(
                self.port.get(),
                115200,
                timeout=0
            )

        except (serial.SerialException, OSError) as error:

            self.status.set(
                f"Could not connect: {error}"
            )

            return

        self.receive_buffer = b""

        self.connected_at = monotonic()
        self.last_reading_at = None
        self.received_bytes = 0

        self.connect_button.config(
            text="Disconnect"
        )

        self.serial_preview.set(
            "USB data: none received"
        )

        self.status.set(
            f"Connected to {self.port.get()}. Waiting for 30 sensor readings..."
        )

    # ---------------------------------------------------------
    # ADC COUNT TO HEATMAP SCALE
    # ---------------------------------------------------------
    @classmethod
    def scale_reading(cls, raw):

        if raw <= 0:
            return 0

        return round(
            min(raw, cls.RAW_MAX)
            * cls.DISPLAY_MAX
            / cls.RAW_MAX
        )

    # ---------------------------------------------------------
    # SERIAL PARSER
    #
    # Expects:
    # Results: [30 integers]
    # ---------------------------------------------------------
    def read_sensors(self):

        if self.connection is None:
            return None

        chunk = self.connection.read(
            min(self.connection.in_waiting, 4096)
        )

        if chunk:

            self.received_bytes += len(chunk)

            preview = chunk.decode(
                "utf-8",
                errors="replace"
            )

            self.serial_preview.set(
                "Latest USB data: "
                + repr(preview[-200:])
            )

        self.receive_buffer += chunk

        lines = self.receive_buffer.split(b"\n")

        self.receive_buffer = lines.pop()

        if len(self.receive_buffer) > 4096:
            self.receive_buffer = b""

        latest = None

        for line in lines:

            text = line.decode(
                "utf-8",
                errors="replace"
            ).strip()

            if not text.startswith("Results:"):
                continue

            try:

                values = json.loads(
                    text.split(":", 1)[1]
                )

            except Exception:
                continue

            if (
                isinstance(values, list)
                and len(values) == self.SENSOR_COUNT
                and all(
                    isinstance(value, int)
                    and self.RAW_MIN <= value <= self.RAW_MAX
                    for value in values
                )
            ):
                latest = values

        return latest

    # ---------------------------------------------------------
    # UPDATE HEATMAP
    # ---------------------------------------------------------
    def update_heatmap(self):

        try:

            readings = self.read_sensors()

        except (
            serial.SerialException,
            OSError
        ) as error:

            self.disconnect()

            self.status.set(
                f"Serial connection lost: {error}"
            )

            readings = None

        if readings is not None:

            self.last_reading_at = monotonic()

            if self.running:

                self.status.set(
                    f"Receiving live readings from {self.connection.port}"
                )

            else:

                self.status.set(
                    f"Receiving live readings from {self.connection.port} (display paused)"
                )

        elif self.connection is not None:

            last_activity = (
                self.last_reading_at
                or self.connected_at
            )

            if (
                last_activity is not None
                and monotonic() - last_activity > 3
            ):

                if self.last_reading_at is not None:

                    self.status.set(
                        "Readings stopped. Display holds last values."
                    )

                elif not self.received_bytes:

                    self.status.set(
                        "Port open, but Pico is sending no data."
                    )

                else:

                    self.status.set(
                        "USB data received, but no valid 30-sensor Results packet detected."
                    )

        if self.running and readings is not None:

            levels = [
                self.scale_reading(value)
                for value in readings
            ]

            data = np.asarray(levels).reshape(
                self.ROWS,
                self.COLS
            )

            self.heatmap.set_data(data)

            for sensor, (raw, scaled) in enumerate(
                zip(readings, levels)
            ):

                self.reading_texts[sensor].set_text(
                    f"S{sensor + 1}\n"
                    f"{scaled}\n"
                    f"{raw}"
                )

            self.canvas.draw_idle()

        self.pending_update = self.root.after(
            self.UPDATE_MS,
            self.update_heatmap
        )

    # ---------------------------------------------------------
    # PAUSE / RESUME
    # ---------------------------------------------------------
    def toggle_running(self):

        self.running = not self.running

        self.pause_button.config(
            text=(
                "Pause"
                if self.running
                else "Resume"
            )
        )

    # ---------------------------------------------------------
    # CLOSE PROGRAM
    # ---------------------------------------------------------
    def close(self):

        if self.pending_update is not None:

            self.root.after_cancel(
                self.pending_update
            )

        self.disconnect()

        self.root.destroy()


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
if __name__ == "__main__":

    root = tk.Tk()

    app = ForceMapApp(root)

    root.mainloop()
