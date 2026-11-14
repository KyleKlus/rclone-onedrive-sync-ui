"""
The desktop shell: everything needed to run the app as one native window.

It wraps the existing backend, it never changes it:

    identity.py        name / icon / id the desktop environment knows the app by
    single_instance.py makes sure only one copy runs at a time
    window.py          the native window (pywebview) around the web UI
    launcher_entry.py  installs the app-menu entry that gives the dock its icon
"""
