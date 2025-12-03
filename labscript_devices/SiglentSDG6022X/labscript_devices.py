from labscript import TriggerableDevice, LabscriptError, set_passed_properties
import labscript_utils.h5_lock
import labscript_utils.properties
import h5py
import numpy as np


class SiglentAWG(TriggerableDevice):
    """Labscript device for the Siglent SDG6022X waveform generator.

    This device supports defining waveform parameters for both channels.
    Parameters are written to the HDF5 file, where the BLACS worker will
    read and apply them at shot time.
    """

    description = 'Siglent SDG6022X Dual Channel AWG'

    @set_passed_properties(
        property_names={
            "connection_table_properties": ["serial_number"],
            "device_properties": [
                "name",
                "channels_attributes",
                "stop_configuration_timeout",
                "trigger_attributes"
            ],
        }
    )
    def __init__(
        self,
        name,
        parent_device,
        connection,
        channels_attributes,
        trigger_attributes,
        stop_configuration_timeout=5.0,
        serial_number=None,
        **kwargs,
    ):
        self.serial_number = serial_number
        self.BLACS_connection = connection
        self.channels_attributes = channels_attributes
        self.trigger_attributes = trigger_attributes

        # Add default entries if missing
        self.trigger_attributes.setdefault('trigger_time', None)
        self.trigger_attributes.setdefault('trigger_duration', 1e-6)
        self.trigger_attributes.setdefault('cycles_1', 1)
        self.trigger_attributes.setdefault('cycles_2', 1)
        self.trigger_attributes.setdefault('trig_delay', 1.435e-6)
        
        super().__init__(name, parent_device, connection, **kwargs)

    # ----------------------------------------------------------------------
    # Triggering
    # ----------------------------------------------------------------------
    def trigger(self, t):
        """Record a hardware trigger time."""
        self.trigger_attributes['trigger_time'] = t
        duration = self.trigger_attributes['trigger_duration']
        delay = self.trigger_attributes['trig_delay']
        super().trigger(t-delay, duration)

    # ----------------------------------------------------------------------
    # Set waveform parameters
    # ----------------------------------------------------------------------
    def update_carrier_waveform(
        self, channel=1, shape='SINE', freq=1e6, amp=1.0, offset=0.0, phase=0.0
    ):
        """Set waveform parameters for the given channel."""
        if channel not in [1, 2]:
            raise LabscriptError(f'Invalid channel: {channel}, must be 1 or 2.')

        # Update waveform parameters
        #self.channels_attributes[f'freq_{channel}'] = freq
        #self.channels_attributes[f'amp_{channel}'] = amp
        #self.channels_attributes[f'off_{channel}'] = offset
        #self.channels_attributes[f'phse_{channel}'] = phase
        #self.channels_attributes[f'shape_{channel}'] = shape

        # Update waveform parameters in dict
        self.channels_attributes.update({
            f'shape_{channel}': shape,
            f'freq_{channel}': freq,
            f'amp_{channel}': amp,
            f'off_{channel}': offset,
            f'phse_{channel}': phase,
        })

    # ----------------------------------------------------------------------
    # Code Generation
    # ----------------------------------------------------------------------
    def generate_code(self, hdf5_file):
        """Write waveform configuration and trigger time to the HDF5 file."""
        self.do_checks()
