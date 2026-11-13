# Native marker Details regression

The captured user interface (UI) comes from run `43366422590`, job
`131691823748`, artifact `14011518633`. It shows the imported synthetic marker
at `0,0`. The existing device connection, test location and authenticated viewer
checks passed. The new scenario failed while waiting for the marker editor;
none of its three complete phases passed.

The hierarchy row opens a native OpenGL radial menu, not the editor. Its Details
control has no UI Automator node. The recorded activity configuration reports
160 dots per inch (DPI); the XML supplies the actual map viewport.

`atak-marker-radial.json` preserves the captured Portable Network Graphics (PNG)
image's decoded red, green, blue and alpha (RGBA) pixels. Its raw screen-capture
header is constructed for offline parser testing, not recorded from a device.
The metadata binds the original PNG and XML hashes. License comments are the
only addition to the captured XML hierarchy.

`../details-icon.json` contains the alpha channel of the official
`icons/details.png` from source revision
`9f6893dd657feacc35ec5de03dad721c2e44170e`. It records the original asset hash,
source path and upstream license reference. The runtime needs only Python's
standard library. It compares both the icon's visible shape and empty background
inside the source-defined second wedge, using the live viewport and DPI.
Unsupported geometry, missing matches and separated matches fail before a tap.

The unchanged captured pixels are the positive regression. Tests that erase or
duplicate the icon are adversarial offline inputs, not device evidence. Passing
them does not qualify import, Broadcast, reverse updates or a new live run.
