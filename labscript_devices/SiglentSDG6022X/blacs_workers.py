#####################################################################
#                                                                   #
# /labscript_devices/SiglentSDG6022X/blacs_worker.py                #
#                                                                   #
# 2025, ICFO                                                        #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org)                                   #
#####################################################################

import numpy as np
import time
import re

import labscript_utils.h5_lock
import h5py
import threading

import sys
import logging
logger = logging.getLogger("SiglentSDG_AWG")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)


from blacs.tab_base_classes import Worker
import labscript_utils.properties

class SiglentSDG6022X(object):
    """Interface class for the Siglent SDG6022X waveform generator.
    Handles communication via USB using SCPI commands over PyVISA.
    """
    def __init__(self, serial_number=None, visa_resource=None):
        """
        Args:
            serial_number (str, optional): Device serial number (for matching specific unit)
            visa_resource (str, optional): VISA resource string (e.g., 'USB0::0xF4EC::0x1102::SDG6XABC1234::INSTR')
        """
        pyvisa = None
        import pyvisa

        self.serial_number = serial_number
        self.visa_resource = visa_resource

        # --------------------------------------------------------------
        # Initialization and teardown
        # --------------------------------------------------------------
        """Initialize VISA connection to Siglent device."""
        self.rm = pyvisa.ResourceManager()

        # Auto-detect if resource not explicitly specified
        if not self.visa_resource:
            resources = self.rm.list_resources()
            candidates = [r for r in resources if 'USB' in r and self.serial_number in r and 'Siglent' in self.rm.open_resource(r).query('*IDN?')]
            logger.debug(f"Candidates: {candidates}")
            if not candidates:
                raise ValueError(f"No Siglent SDG6022X instrument with SN:{self.serial_number} found via USB.")
            self.visa_resource = candidates[0]

        # Connect
        self.inst = self.rm.open_resource(self.visa_resource)
        self.inst.timeout = 5000  # ms

        idn = self.inst.query('*IDN?').strip()
        logger.info(f"Connected to {idn}")
        self.inst.write('*CLS')  # clear status

    def close(self):
        """Safely close the VISA connection."""
        try:
            self.set_output(state1=False, state2=False)
            logger.debug("Outputs disabled before closing.")
        except Exception:
            pass
        if self.inst:
            self.inst.close()
        if self.rm:
            self.rm.close()
        logger.info("Siglent SDG6022X connection closed.")

    # --------------------------------------------------------------
    # Basic SCPI communication helpers
    # --------------------------------------------------------------
    def write(self, cmd: str):
        """Send a SCPI command to the instrument."""
        self.inst.write(cmd)
        # small wait for device to execute if needed (Siglents can be slow with back-to-back commands)
        # time.sleep(0.01) 

    def query(self, cmd: str) -> str:
        """Query a SCPI command and return the result as string."""
        resp = self.inst.query(cmd).strip()
        time.sleep(0.01)
        return resp

    # --------------------------------------------------------------
    # Configuration Methods
    # --------------------------------------------------------------

    def set_waveform(self, channel, wf):
        """Set basic waveform parameters for a given channel, with caching to avoid redundant writes."""
        new_conf = tuple(wf.values())
        if getattr(self, f'_last_conf_{channel}', None) == new_conf:
            # Skip identical setup to reduce USB I/O
            return

        cmd = f"C{channel}:BSWV WVTP,{wf['shape']},FRQ,{wf['freq']},AMP,{wf['amp']},OFST,{wf['offset']},PHSE,{wf['phase']}"
        self.write(cmd)
        setattr(self, f'_last_conf_{channel}', new_conf)
        logger.info(f"CH{channel} → shape={wf['shape']}, freq={wf['freq']:.6g} Hz, "
              f"amp={wf['amp']} Vpp, offset={wf['offset']} V, phase={wf['phase']}°")

    def set_output(self, channel = 1, state = False):
        """Enable/disable channel outputs."""
        if self.get_output_state(channel=channel) == state:
            # Skip reduce USB I/O
            return 

        self.write(f"C{channel}:OUTP {'ON' if state else 'OFF'}")
        logger.debug(f"Outputs set -> CH{channel}: {'ON' if state else 'OFF'}")
        
    def get_output_state(self, channel=1) -> bool:
        """Return True if channel output is ON."""
        resp = self.query(f"C{channel}:OUTP?")
        resp_split = re.split(',| ', resp)
        return "ON" in resp_split

    def get_waveform(self, channel=1):
        """Return current waveform parameters for a channel."""
        resp = self.query(f"C{channel}:BSWV?")
        resp_split = re.split(',| ', resp)
        data = {resp_split[i]: resp_split[i+1] for i in range(1,len(resp_split),2)}
        return {
            'WVTP': data.get('WVTP', ''),
            'FRQ': data.get('FRQ', ''),
            'AMP': data.get('AMP', ''),
            'OFST': data.get('OFST', ''),
            'PHSE': data.get('PHSE', '')
        }

    # --------------------------------------------------------------
    # Modulate Wave Command
    # --------------------------------------------------------------

    # To be written
    
    # --------------------------------------------------------------
    # Burst / Triggered operation
    # --------------------------------------------------------------

    def set_carrier_waveform(self, channel, wf):
        """Set basic waveform parameters for a given channel, with caching to avoid redundant writes."""
        new_conf = tuple(wf.values())
        if getattr(self, f'_last_conf_carrier_{channel}', None) == new_conf:
            # Skip identical setup to reduce USB I/O
            return

        cmd = (
            f"C{channel}:BTWV CARR,WVTP,{wf['shape']},CARR,FRQ,{wf['freq']},"
            f"CARR,AMP,{wf['amp']},CARR,OFST,{wf['offset']},CARR,PHSE,{wf['phase']}"
        )
        self.write(cmd)
        setattr(self, f'_last_conf_carrier_{channel}', new_conf)
        logger.info(f"Carrier{channel} → shape={wf['shape']}, freq={wf['freq']:.6g} Hz, "
              f"amp={wf['amp']} Vpp, offset={wf['offset']} V, phase={wf['phase']}°")

    def configure_burst_2ch(self, ch1_params=None, ch2_params=None):
        """Configure burst mode for both channels simultaneously with independent settings."""
        # Default parameters if not provided
        ch1_params = ch1_params or {'cycles': 1, 'trigger_source': 'EXT'}
        ch2_params = ch2_params or {'cycles': 1, 'trigger_source': 'EXT'}

        new_conf = (tuple(ch1_params.values()), tuple(ch1_params.values()))
        if getattr(self, f'_last_conf_burst', None) != new_conf:
            # Skip identical setup to reduce USB I/O
            def burst_cmd(channel, cycles, trigger_source):
                """Return a formatted burst configuration string for a given channel."""
                if cycles == 0:
                    gate_mode = "GATE"
                    time_str = ""
                else:
                    gate_mode = "NCYC"
                    time_str = f",TIME,{cycles}"

                if trigger_source == 'MAN':
                    trigger_param = "TRMD,RISE"
                else:
                    trigger_param = "EDGE,RISE"
                return (
                   f"C{channel}:BTWV STATE,ON,GATE_NCYC,{gate_mode}{time_str},"
                   f"TRSR,{trigger_source},DLAY,0,{trigger_param}"
                )

            # Send batched write for efficiency
            self.write(burst_cmd(1, ch1_params.get('cycles', 1), ch1_params.get('trigger_source', 'EXT')))
            self.write(burst_cmd(2, ch2_params.get('cycles', 1), ch2_params.get('trigger_source', 'EXT')))
            logger.info(f"  CH1 → cycles={ch1_params['cycles']}, trigger={ch1_params['trigger_source']}")
            logger.info(f"  CH2 → cycles={ch2_params['cycles']}, trigger={ch2_params['trigger_source']}")

        #self.write("C1:BTWV STATE,ON")
        #self.write("C2:BTWV STATE,ON")
        self.set_output(channel = 1, state = True)
        self.set_output(channel = 2, state = True)

        setattr(self, f'_last_conf_burst', new_conf)
        logger.info("Burst mode configured")

    def configure_BufferThread(self, wf1, ch1_params, wf2, ch2_params):
        """Runs the AWG configuration steps in background."""
        self.set_carrier_waveform(channel = 1, wf = wf1)
        self.set_carrier_waveform(channel = 2, wf = wf2)
        self.configure_burst_2ch(ch1_params, ch2_params)

    def trigger(self,channel=1):
        """Manually issue a trigger (if in burst mode with manual trigger source)."""
        self.write(f"C{channel}:BTWV MTRIG")
        logger.info("Manual trigger issued.")

    # --------------------------------------------------------------
    # Utility methods
    # --------------------------------------------------------------
    def reset(self):
        """Reset the instrument to default state."""
        self.write("*RST")
        time.sleep(0.5)
        logger.info("Instrument reset to default state.")


class SiglentAWGWorker(Worker):
    # Subclasses may override this if their interface class takes only the serial number
    # as an instantiation argument
    interface_class = SiglentSDG6022X

    def init(self):
        logger.info("Finding Siglent SDG Instrument...")
        self.awg = self.interface_class(self.serial_number)
        self.configuration_thread = None
        self.stop_configuration_timeout = None
        # Apply default configuration for each channel

        try:
            wf1 = {
            'shape':  self.channels_attributes.get('shape_1', 'SINE'),
            'freq':   float(self.channels_attributes.get('freq_1', 1e6)),
            'amp':    float(self.channels_attributes.get('amp_1', 1.0)),
            'offset': float(self.channels_attributes.get('off_1', 0.0)),
            'phase':  float(self.channels_attributes.get('phse_1', 0.0)),
            }
            wf2 = {
                'shape':  self.channels_attributes.get('shape_2', 'SINE'),
                'freq':   float(self.channels_attributes.get('freq_2', 1e6)),
                'amp':    float(self.channels_attributes.get('amp_2', 1.0)),
                'offset': float(self.channels_attributes.get('off_2', 0.0)),
                'phase':  float(self.channels_attributes.get('phse_2', 0.0)),
            }

            # Apply waveform parameters
            self.awg.set_output(channel=1, state=False)
            self.awg.set_output(channel=2, state=False)
            self.awg.set_waveform(channel=1, wf=wf1)
            self.awg.set_waveform(channel=2, wf=wf2)

        except Exception as e:
            logger.error(f"Failed to configure channels: {e}")
    # --------------------------------------------------------------
    # Labscript Methods
    # --------------------------------------------------------------

    def transition_to_buffered(self, device_name, h5file, initial_values, fresh):
        """Prepare the AWG for a buffered (triggered) experiment."""
        self.h5file = h5file  
        self.device_name = device_name

        logger.info(f"Transitioning {device_name} to buffered mode...")

        # Load configuration from HDF5
        with h5py.File(h5file, 'r') as hdf5_file:
            self.device_properties = labscript_utils.properties.get(
                hdf5_file, device_name, 'device_properties'
            )
        channels_attributes = self.device_properties['channels_attributes']
        trigger_attributes = self.device_properties['trigger_attributes']
        self.stop_configuration_timeout = self.device_properties['stop_configuration_timeout']

        if not self.device_properties:
            logger.error("No waveform configuration found in HDF5 file.")
            raise RuntimeError

        # Update carrier waveform configuration 
        wf1 = {
            'shape':  channels_attributes.get('shape_1', 'SINE'),
            'freq':   float(channels_attributes.get('freq_1', 1e6)),
            'amp':    float(channels_attributes.get('amp_1', 1.0)),
            'offset': float(channels_attributes.get('off_1', 0.0)),
            'phase':  float(channels_attributes.get('phse_1', 0.0)),
        }
        wf2 = {
            'shape':  channels_attributes.get('shape_2', 'SINE'),
            'freq':   float(channels_attributes.get('freq_2', 1e6)),
            'amp':    float(channels_attributes.get('amp_2', 1.0)),
            'offset': float(channels_attributes.get('off_2', 0.0)),
            'phase':  float(channels_attributes.get('phse_2', 0.0)),
        }

        # Configure both channels independently for burst mode
        ch1_params = {'cycles': trigger_attributes.get('cycles_1', 1), 'trigger_source': 'EXT'}
        ch2_params = {'cycles': trigger_attributes.get('cycles_2', 1), 'trigger_source': 'EXT'}

        # Batch program both channels
        self.configuration_thread = threading.Thread(
            target=self.awg.configure_BufferThread,
            args=(wf1, ch1_params, wf2, ch2_params),
            daemon=True,
        )
        self.configuration_thread.start()
        return {}


    def transition_to_manual(self):
        """Called when BLACS switches back to manual mode."""
        logger.info("Transitioning AWG to manual mode (safe state).\n")

        if self.configuration_thread:
            self.configuration_thread.join(timeout=self.stop_configuration_timeout)

        if self.configuration_thread.is_alive():
            self.configuration_thread.join()
            self.awg.abort()
            logger.warning("Configuration thread did not finish before timeout — aborting AWG.")


        # Disable burst/trigger mode on both channels
        #self.awg.set_output(channel=1, state=False)  # optionally disable output
        #self.awg.set_output(channel=2, state=False)
        #self.awg.write(f"C1:BTWV STATE,OFF")
        #self.awg.write(f"C2:BTWV STATE,OFF")
        
        self.configuration_thread = None
        self.stop_configuration_timeout = None
        self.h5file = None  
        self.device_name = None
        self.device_properties = None
        setattr(self, f'_last_conf_carrier_1', None)
        setattr(self, f'_last_conf_carrier_2', None)
        setattr(self, f'_last_conf_1', None)
        setattr(self, f'_last_conf_2', None)
        setattr(self, f'_last_conf_burst', None)

        return True

    def set_waveform_2ch(self, wf1, wf2):
        """Call AWG to set both waveforms in a single command and enable outputs."""
        self.awg.set_waveform(channel=1, wf=wf1)
        self.awg.set_waveform(channel=2, wf=wf2)
        self.awg.set_output(channel=1, state=True)
        self.awg.set_output(channel=2, state=True)


    def program_manual(self, values):
        """Handle BLACS manual control updates."""
        return {}

    def abort(self):
        self.awg.set_output(channel=1, state=False)
        self.awg.set_output(channel=2, state=False)
        logger.info('aborting!')
        return True

    def abort_buffered(self):
        return self.abort()

    def abort_transition_to_buffered(self):
        logger.info('abort_transition_to_buffered: ...')
        return self.abort()

    def shutdown(self):
        if self.awg:
            self.awg.reset()
            self.awg.close()
            self.awg = None
            self.h5_file = None
