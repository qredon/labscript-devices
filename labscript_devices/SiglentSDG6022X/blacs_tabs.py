#####################################################################
#                                                                   #
# /labscript_devices/SiglentSDG6022X/blacs_tab.py                   #
#                                                                   #
# 2025, ICFO                                                        #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org)                                   #
#####################################################################

from blacs.device_base_class import DeviceTab
from blacs.tab_base_classes import define_state, MODE_MANUAL

import labscript_utils.h5_lock
import h5py

from qtutils.qt.QtWidgets import QWidget, QGridLayout, QLabel, QLineEdit, QComboBox, QPushButton, QDoubleSpinBox

import labscript_utils.properties

class SiglentAWGTab(DeviceTab):
    """BLACS Tab for controlling the Siglent SDG6022X AWG."""

    # Path to the worker class
    worker_class = 'labscript_devices.SiglentSDG6022X.blacs_workers.SiglentAWGWorker'

    def initialise_GUI(self):
        """Set up a manual control GUI for the AWG."""
        layout = self.get_tab_layout()

        # Container widget
        self.manual_widget = QWidget()
        grid = QGridLayout()
        self.manual_widget.setLayout(grid)
        layout.addWidget(self.manual_widget)

        self.controls = {}  # store widgets for easy access

        # Channels
        for ch in [1, 2]:
            row_offset = (ch - 1) * 6
            grid.addWidget(QLabel(f"Channel {ch}:"), row_offset, 0)

            # Frequency
            grid.addWidget(QLabel("Freq (MHz):"), row_offset + 1, 0)
            freq_spin = QDoubleSpinBox()
            freq_spin.setRange(0, 200)
            freq_spin.setDecimals(8)
            freq_spin.setValue(1.0)
            grid.addWidget(freq_spin, row_offset + 1, 1)
            self.controls[f'freq_{ch}'] = freq_spin

            # Amplitude
            grid.addWidget(QLabel("Amp:"), row_offset + 2, 0)
            amp_spin = QDoubleSpinBox()
            amp_spin.setRange(0, 10)
            amp_spin.setDecimals(3)
            amp_spin.setValue(1.0)
            grid.addWidget(amp_spin, row_offset + 2, 1)
            self.controls[f'amp_{ch}'] = amp_spin

            # Offset
            grid.addWidget(QLabel("Offset:"), row_offset + 3, 0)
            off_spin = QDoubleSpinBox()
            off_spin.setRange(-10, 10)
            off_spin.setDecimals(3)
            off_spin.setValue(0.0)
            grid.addWidget(off_spin, row_offset + 3, 1)
            self.controls[f'off_{ch}'] = off_spin

            # Phase
            grid.addWidget(QLabel("Phase (deg):"), row_offset + 4, 0)
            phase_spin = QDoubleSpinBox()
            phase_spin.setRange(0, 360)
            phase_spin.setDecimals(2)
            phase_spin.setValue(0.0)
            grid.addWidget(phase_spin, row_offset + 4, 1)
            self.controls[f'phse_{ch}'] = phase_spin

            # Shape
            grid.addWidget(QLabel("Shape:"), row_offset + 5, 0)
            shape_combo = QComboBox()
            shape_combo.addItems(["SINE", "SQUARE", "RAMP", "PULSE", "NOISE", "ARB","DC"])
            grid.addWidget(shape_combo, row_offset + 5, 1)
            self.controls[f'shape_{ch}'] = shape_combo

        # Apply button
        apply_btn = QPushButton("Apply to AWG")
        apply_btn.clicked.connect(self.on_apply_manual_clicked)
        layout.addWidget(apply_btn)


    def on_apply_manual_clicked(self, button):
        """Collect parameters from GUI and apply both channels (manual mode only)."""
        if self.mode != MODE_MANUAL:
            print("[WARN] Cannot apply settings: not in manual mode.")
            return

        wf1 = {
            'shape':  self.controls['shape_1'].currentText(),
            'freq':   float(self.controls['freq_1'].value()) * 1e6,
            'amp':    float(self.controls['amp_1'].value()),
            'offset': float(self.controls['off_1'].value()),
            'phase':  float(self.controls['phse_1'].value())
        }

        wf2 = {
            'shape':  self.controls['shape_2'].currentText(),
            'freq':   float(self.controls['freq_2'].value()) * 1e6,
            'amp':    float(self.controls['amp_2'].value()),
            'offset': float(self.controls['off_2'].value()),
            'phase':  float(self.controls['phse_2'].value())
        }

        self.apply_manual_settings(wf1, wf2)


    @define_state(MODE_MANUAL, queue_state_indefinitely=True, delete_stale_states=True)
    def apply_manual_settings(self, wf1, wf2):
        """Send manual settings for both channels (batched)."""
        yield self.queue_work(
            self.primary_worker,
            'set_waveform_2ch',
            wf1=wf1,
            wf2=wf2
        )

    def initialise_workers(self):
        table = self.settings['connection_table']
        connection_table_properties = table.find_by_name(self.device_name).properties
        # The device properties can vary on a shot-by-shot basis, but at startup we will
        # initially set the values that are configured in the connection table, so they
        # can be used for manual mode acquisition:
        with h5py.File(table.filepath, 'r') as f:
            device_properties = labscript_utils.properties.get(
                f, self.device_name, "device_properties"
            )

        # Set up BLACS workers and pass initial connection table properties."""
        # Get connection table properties (e.g. serial_number)
        worker_initialisation_kwargs = {
            'serial_number': connection_table_properties['serial_number'],
            'channels_attributes': device_properties['channels_attributes'],
        }

        # Create worker and assign as primary
        self.create_worker(
            'main_worker', self.worker_class, worker_initialisation_kwargs
        )
        self.primary_worker = 'main_worker'