import tkinter as tk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class ForceMapApp:
    ROWS = 6
    COLS = 5
    UPDATE_MS = 100

    def __init__(self, root):
        self.root = root
        self.root.title("Force Sensor Array")
        self.running = True
        self.pending_update = None

        figure = Figure(figsize=(7, 5), dpi=100)
        axes = figure.add_subplot(111)

        # Keep the color scale fixed so colors remain comparable over time.
        self.heatmap = axes.imshow(
            np.zeros((self.ROWS, self.COLS)),
            cmap="inferno",
            vmin=0,
            vmax=8191,
            interpolation="lanczos",
            origin="upper",
        )

        axes.set(
            title="Force Sensor Readings",
            xlabel="Column",
            ylabel="Row",
            xticks=range(self.COLS),
            yticks=range(self.ROWS),
            xticklabels=range(1, self.COLS + 1),
            yticklabels=range(1, self.ROWS + 1),
        )

        figure.colorbar(self.heatmap, ax=axes, label="Raw sensor reading")
        figure.tight_layout()

        self.canvas = FigureCanvasTkAgg(figure, master=root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.pause_button = tk.Button(
            root, text="Pause", command=self.toggle_running
        )
        self.pause_button.pack(pady=8)

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.update_heatmap()

    def read_sensors(self):
        """Replace this with real readings arranged as 5 rows × 6 columns."""
        return np.random.randint(0, 8192, size=(self.ROWS, self.COLS))

    def update_heatmap(self):
        if self.running:
            readings = self.read_sensors()
            self.heatmap.set_data(readings)
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
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ForceMapApp(root)
    root.mainloop()