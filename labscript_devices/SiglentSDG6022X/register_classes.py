import labscript_devices

labscript_devices.register_classes(
    'SiglentAWG',
    BLACS_tab='labscript_devices.SiglentSDG6022X.blacs_tabs.SiglentAWGTab',
    runviewer_parser=None
)
