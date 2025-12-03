#####################################################################
#                                                                   #
# /labscript_devices/HamamatsuCamera/blacs_workers.py               #
#                                                                   #
# Copyright 2019, Monash University and contributors                #
#                                                                   #
# This file is part of labscript_devices, in the labscript suite    #
# (see http://labscriptsuite.org), and is licensed under the        #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################

# Original imaqdx_camera server by dt, with modifications by rpanderson and cbillington.
# Refactored as a BLACS worker by cbillington
# Hamamatsu (pylablib wrapper) implementation by qredon

import numpy as np
from labscript_utils import dedent

import os
import sys

import logging
logger = logging.getLogger("Hamamatsu_Camera")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)


from labscript_devices.IMAQdxCamera.blacs_workers import IMAQdxCameraWorker


# Don't import API yet so as not to throw an error, allow worker to run as a dummy
# device, or for subclasses to import this module to inherit classes without requiring API
pylablib = None

def int_to_camera_id(cam_int: int) -> str:
    """Convert the integer ID back to the original string."""
    # Calculate how many bytes are needed to represent the integer
    length = (cam_int.bit_length() + 7) // 8
    return cam_int.to_bytes(length, byteorder='big').decode('utf-8')

class Hamamatsu_Camera(object):
    def __init__(self, serial_number):
        """The backend hardware interface class for the HamamatsuCamera.
        
        This class handles all of the API/hardware implementation details for the
        corresponding labscript device. It is used by the BLACS worker to send
        appropriate API commands to the camera for the standard BLACS camera operations
        (i.e. transition_to_buffered, get_attributes, snap, etc).
        """
        from pylablib.devices.DCAM import DCAM, DCAMCamera

        num_cams = DCAM.get_cameras_number()
        cam_id_str = int_to_camera_id(serial_number)
        if num_cams == 0:
            raise ValueError("No Hamamatsu DCAM cameras detected.")
    
        # Find requested serial
        available = []
        cam_id = None
        
        for idx in range(num_cams):
            cam_tmp = DCAMCamera(idx)
            vendor, model, sn, camera_version = cam_tmp.get_device_info()
            available.append(sn)

            logger.debug(f"Found camera #{idx}: SN={sn}, model={model}")

            if sn == cam_id_str:
                cam_id = idx

            cam_tmp.close()

        if cam_id is None:
            raise ValueError(
                f"Camera with serial {serial_number} not found. "
                f"Available: {available}"
            )

        logger.info(f"Opening camera #{cam_id} ({cam_id_str})")

        # Open the selected camera
        self.cam = DCAMCamera(cam_id)
        self.cam.open()

        self._abort_acquisition = False
        self.exception_on_failed_shot = True
        self.timeout_s = 5

    ## This shows camera attributes only, if needed get_full_info(include=-10) give access to all parameters (Frame,status)
    def show_attributes(self, writable_only=False):
        """Print all camera attributes
        Print:
            feature_name: 'value': <> | 'visibility': <> | 'writable': <> | 'readable': <>
        """
        attrs = {}
        features = self.cam.get_all_attributes(copy=True)
            
        for name, attr in features.items():
            # write filtering
            if writable_only and not attr.writable:
                continue
            is_readable = attr.readable
            # Safely try to get value if readable
            try:
                # Read value
                value = attr.get_value(enum_as_str=True) if is_readable else '<Not readable>'
        
            except Exception as e:
                value = '<Error>'
                # Add some info to the exception:
                raise Exception(f"Failed to get attribute {name}") from e   
            
            print(f"{name:30s} | {value} | readable = {is_readable} | writable={attr.writable}")       
        
        return None
        
    def get_attribute_names(self, writable_only=False):
        """Return a list camera attributes filtered by writability.
        Args:
            writable_only (bool, optional): If True, only include writable features.
        Returns:
            list: [feature_names]
        """
        attr_names = []
        attrs = self.cam.get_all_attributes(copy=True)

        for name, attr in attrs.items():
            if writable_only and not attr.writable:
                continue
            attr_names.append(name)
            
        logger.debug(f"Retrieved attribute names (writable_only={writable_only}): {attr_names}")
        return attr_names
        
    def get_attribute(self, name):
        """Return a single camera attribute.
        Args:
            name (str): Name of the camera feature to query.
        Returns:
            attribute value
        """
        try:
            return self.cam.get_attribute_value(name, enum_as_str=True)
        except Exception as e:
            logger.error(f"Failed to read attribute '{name}': {e}")
            raise
        
    def get_available_EnumEntries(self, name):
        try:
            attr = self.cam.get_attribute(name)
            return list(attr.labels.keys())
        except Exception as e:
            logger.error(f"Failed to retrieve enum entries for '{name}': {e}")
            raise

    def set_attribute(self, name, value):
        """Set a single camera attribute, with type safety and visibility checks.
        Args:
            name (str): Name of the camera feature to set.
            value (any): Value to assign. For Enum or Command features, use strings.
        Returns:
            bool: True if successfully set or executed, False otherwise.
        """
        
        # Attempt to retrieve feature
        try:
            attr = self.cam.get_attribute(name)
        except Exception as e:
            logger.error(f"Failed to get attribute {name}: {e}")
            return False
    
        if not attr.writable:
            logger.warning(f"Attribute '{name}' is not writable.")
            return False

        if attr.kind == "enum":
            available  = self.get_available_EnumEntries(name)
            if value not in available:
                logger.warning(f"Invalid enum value {value} for {name}. Must be one of {available}")
                return False
            attr.set_value(attr.labels[value])
            
        elif attr.kind in ("int", "float") and isinstance(value, (int, float)):
            attr.set_value(value)

        else:
            logger.warning(f"Unsupported feature type '{attr.kind}' for attribute '{name}'.")
            return False
                
        logger.debug(f"Set {name} = {value}")
        return True

    def set_attributes(self, attr_dict):
       for k, v in attr_dict.items():
           self.set_attribute(k, v)

    # ## Enum should be integer (original method, requires enum as int)
    # def set_attributes(self, attr_dict):
    #     self.cam.set_all_attribute_values(attr_dict)

    def configure_acquisition(self, continuous=True, buffer_count=10):
        """Configure and prepare the camera for acquisition.
        Args:
            continuous (bool): If True, camera runs continuously.
                               If False, single-frame mode or multi-frame mode.
            buffer_count (int): Number of frame buffers to queue.
        """
        if self.cam.acquisition_in_progress():
            raise RuntimeError("Camera acquisition already in progress.")
        
        # Set acquisition mode
        mode = 'sequence' if continuous else 'snap'
        mode_print = 'continous' if mode=='sequence' else 'snap'

        self.cam.setup_acquisition(mode=mode, nframes=buffer_count)

        # Store image format info for later decoding
        #self.width = self.get_attribute("Width")
        #self.height = self.get_attribute("Height")
        #self.pixel_format = self.get_attribute("PixelFormat")
        
        # Start acquisition
        acquisition_param = self.cam.get_acquisition_parameters()
        logger.info(f"Acquisition configured: mode={mode_print}, buffers={acquisition_param['nframes']}")
        self.cam.start_acquisition()

    def grab(self):
        """ grab and return single image during pre-configured acquisition
        Returns:
            numpy.array: Acquired image
        """
        self.cam.wait_for_frame(since='lastread', nframes=1,
                                timeout=self.timeout_s,
                                error_on_stopped=True)
        
        info = self.cam.get_transfer_info()
        logger.debug(f'{info[1]} image(s) acquired with: {self.cam.get_roi()}, exposure {self.cam.get_exposure()} s')
        img = self.cam.read_newest_image()
        return img
        
    def grab_multiple(self, n_images, images):
        """Grab n_images into images array during buffered acquistion.
        Args:
            n_images (int): Number of captured images.
            images (list): Empty list to fill with images
        """
        logger.info(f"Attempting to grab {n_images} images...")
            
        self.cam.wait_for_frame(since='lastread', nframes=n_images,
                                timeout=self.timeout_s,
                                error_on_stopped=True)
        
        info = self.cam.get_transfer_info()
        transferred = info[1]
        if transferred < n_images:
            raise RuntimeError(
                f"Camera delivered only {transferred} frames out of {n_images}"
            )
        imgs = self.cam.read_multiple_images(rng=(0, n_images),
                                             peek=False,
                                             missing_frame='skip')

        images += imgs
        logger.info(f'{info[1]} image(s) acquired with: {self.cam.get_roi()}, exposure {self.cam.get_exposure()} s')
        
    def snap(self):
        """ Acquire a single image and return it
        Returns:
            numpy.array: Acquired image
        """
        logger.info("Snapping single image...")
        img = self.cam.snap(self.timeout_s) # also stop acquisition
        logger.info(f'Single image acquired with: {self.cam.get_roi()}, exposure {self.cam.get_exposure()} s')
        return img
    
    def stop_acquisition(self):
        """Stop streaming of camera"""
        if self.cam.acquisition_in_progress():
            self.cam.stop_acquisition()
            self.cam.clear_acquisition()
            logger.info('Stopping acquisition...')

            
    def abort_acquisition(self):
        """Set _abort_acquisition to True"""
        logger.info('Aborting acquisition...')
        self.stop_acquisition()
        self._abort_acquisition = True
        
    def close(self):
        """Safely stop acquisition, close the camera connection."""
        if self.cam is None:
            return
        # Stop acquisition if running and clear it
        self.stop_acquisition()
        # Close the camera
        self.cam.close()
        self.cam = None
        logger.info("Camera connection closed.")
    


class HamamatsuCameraWorker(IMAQdxCameraWorker):
    """Hamamatsu API Camera Worker.

    Inherits from IMAQdxCameraWorker."""
    interface_class = Hamamatsu_Camera