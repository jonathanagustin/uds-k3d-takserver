#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded UI actions for the pinned official ATAK file browser and marker panes."""
import importlib.util
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

spec = importlib.util.spec_from_file_location('scenario', Path(__file__).with_name('android-interoperability.py'))
scenario = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scenario)


def select(tree, *, rid=None, text=None):
    matches = []
    for node in tree.iter('node'):
        if node.get('enabled') != 'true' or node.get('visible-to-user') == 'false':
            continue
        if rid and not node.get('resource-id', '').endswith(':id/' + rid):
            continue
        if text and text not in (node.get('text'), node.get('content-desc')):
            continue
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if bounds and int(bounds[3]) > int(bounds[1]) and int(bounds[4]) > int(bounds[2]):
            matches.append(node)
    if len(matches) != 1:
        raise LookupError('expected one enabled UI node')
    return matches[0]


def loadout_list_button(tree):
    """The pinned Tools toolbar's last action pops to the labelled loadout list.

    LoadoutToolsDropDown.getButtons() appends settings after edit/export/layout;
    DropDownNavigationStack appends its close button. The icons have no accessible
    labels, so require that exact live hierarchy rather than fixed coordinates.
    """
    select(tree, rid='nav_stack_toolbar_title', text='Tools')
    select(tree, rid='tools_list')
    toolbar = select(tree, rid='nav_stack_toolbar_buttons')
    buttons = list(toolbar)
    if not 3 <= len(buttons) <= 5:
        raise LookupError('unexpected pinned Tools toolbar shape')
    for index, button in enumerate(buttons):
        if (button.get('class') != 'android.widget.ImageButton'
                or button.get('clickable') != 'true'):
            raise LookupError('unexpected pinned Tools toolbar action')
        select(button)  # Exactly one enabled, visible, positive-bounds node.
        expected = ':id/nav_stack_close' if index == len(buttons)-1 else ''
        rid = button.get('resource-id', '')
        if (expected and not rid.endswith(expected)) or (not expected and rid):
            raise LookupError('unexpected pinned Tools toolbar order')
    return buttons[-2]


def local_import_button(tree):
    return first_import_tile(tree, 'Select Import Type', 5)


def first_import_tile(tree, title, count):
    """Pinned ImportManagerView adds Local SD first; TileButtonDialog keeps order."""
    select(tree, rid='alertTitle', text=title)
    container = select(tree, rid='container')
    rows = list(container)
    if len(rows) != 1 or len(rows[0]) != count:
        raise LookupError('unexpected pinned import tile layout')
    buttons = list(rows[0])
    previous_right = None
    vertical = None
    for button in buttons:
        if (button.get('class') != 'android.view.View'
                or button.get('clickable') != 'true' or list(button)
                or button.get('resource-id') or button.get('text')
                or button.get('content-desc')):
            raise LookupError('unexpected pinned import tile')
        select(button)
        left, top, right, bottom = map(int, re.findall(r'\d+', button.get('bounds')))
        if ((previous_right is not None and left != previous_right)
                or (vertical is not None and vertical != (top, bottom))):
            raise LookupError('unexpected pinned import tile order')
        previous_right, vertical = right, (top, bottom)
    return buttons[0]


class AndroidUI:
    def __init__(self, output, device='atak-device-adb.atak.svc.cluster.local:5555', pod='atak-demo-adb'):
        self.output = Path(output)
        self.prefix = ['uds', 'zarf', 'tools', 'kubectl', 'exec', '-n', 'atak', pod, '--', 'adb', '-s', device]

    def adb(self, *command):
        return scenario.run_bounded(self.prefix + list(command), timeout=12)

    def apk_identity(self):
        installed = self.adb('shell', 'pm', 'path', 'com.atakmap.app.civ').decode().strip()
        match = re.fullmatch(r'package:([/A-Za-z0-9._=+-]+)', installed)
        if match is None:
            raise ValueError('expected one installed ATAK base APK')
        actual = self.adb('shell', 'sha256sum', match[1]).decode().split()[0]
        image = scenario.run_bounded(self.prefix[:-3] + ['sha256sum', '/atak-civ.apk'], timeout=12).decode().split()[0]
        if not re.fullmatch('[0-9a-f]{64}', actual) or actual != image:
            raise ValueError('installed ATAK APK differs from the existing driver image')
        return actual

    def tree(self):
        self.adb('shell', 'uiautomator', 'dump', '/sdcard/scenario-ui.xml')
        payload = self.adb('exec-out', 'cat', '/sdcard/scenario-ui.xml')
        if b'certificate invalid' in payload.lower() or b'unable to validate' in payload.lower():
            raise ValueError('certificate prompt blocks scenario')
        return ET.fromstring(payload)

    def find(self, seconds=10, **selector):
        deadline = time.monotonic() + seconds
        while True:
            try:
                return select(self.tree(), **selector)
            except LookupError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.25)

    def tap(self, **selector):
        self.tap_node(self.find(**selector))

    def tap_node(self, node):
        select(node)
        x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.get('bounds')))
        self.adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))

    def capture(self, name):
        self.output.mkdir(parents=True, exist_ok=True)
        self.adb('shell', 'uiautomator', 'dump', '/sdcard/scenario-ui.xml')
        (self.output / (name + '.xml')).write_bytes(self.adb('exec-out', 'cat', '/sdcard/scenario-ui.xml'))
        image = self.adb('exec-out', 'screencap', '-p')
        if not image.startswith(b'\x89PNG\r\n\x1a\n') or not image.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82'):
            raise ValueError('device screenshot is not a complete PNG')
        if sum(p.stat().st_size for p in self.output.glob('*') if p.is_file()) + len(image) > 12*1024*1024:
            raise ValueError('UI evidence budget exceeded')
        (self.output / (name + '.png')).write_bytes(image)

    def tool(self, name):
        # Hamburger opens CURRENT-loadout overflow, which excludes toolbar tools
        # such as Import and Overlays. Its settings action opens Toolbars; the
        # labelled All tools & plugins row then opens the complete native grid.
        self.tap(rid='tak_nav_menu_button')
        self.find(rid='nav_stack_toolbar_title', text='Tools')
        self.tap_node(loadout_list_button(self.tree()))
        self.tap(rid='toolbar_title_item_text', text='All tools & plugins')
        for _ in range(6):
            try:
                listing = select(self.tree(), rid='tools_list')
                select(listing, rid='tak_nav_item_text', text=name)
                self.tap(rid='tak_nav_item_text', text=name)
                return
            except LookupError:
                listing = self.find(rid='tools_list')
                x1, y1, x2, y2 = map(int, re.findall(r'\d+', listing.get('bounds')))
                self.adb('shell', 'input', 'swipe', str((x1+x2)//2), str(y1+4*(y2-y1)//5), str((x1+x2)//2), str(y1+(y2-y1)//5), '300')
        raise LookupError('tool absent from bounded All Tools scan')

    def confirm_file_selected(self, filename):
        tree = self.tree()
        node = select(tree, rid='importManagerBrowserFileName', text=filename)
        parents = {child: parent for parent in tree.iter() for child in parent}
        while node in parents:
            node = parents[node]
            boxes = [child for child in node.iter('node') if child.get('resource-id', '').endswith(':id/importManagerBrowserFileSelected')]
            if boxes:
                if len(boxes) != 1 or boxes[0].get('checked') != 'true':
                    raise ValueError('exact package row is not selected')
                return
        raise ValueError('package selection checkbox absent')

    def import_package(self):
        self.tool('Import')
        self.find(rid='alertTitle', text='Select Import Type')
        self.tap_node(local_import_button(self.tree()))
        self.tap(rid='phone')
        for _ in range(5):
            current = self.find(rid='importBrowserCurrentDirectory').get('text', '').rstrip('/')
            if current in ('/sdcard', '/storage/emulated/0', '/storage/self/primary'):
                break
            self.tap(rid='importManagerFileBrowserUpButton')
        else:
            raise ValueError('file browser did not reach shared storage')
        self.tap(rid='importManagerBrowserFileName', text='Download')
        self.tap(rid='importManagerBrowserFileName', text='atak-synthetic-scenario.dpk')
        self.confirm_file_selected('atak-synthetic-scenario.dpk')
        self.tap(text='OK')
        self.find(rid='alertTitle', text='Suggested Import Strategy')
        self.tap_node(first_import_tile(self.tree(), 'Suggested Import Strategy', 3))

    def hide_keyboard(self):
        state = self.adb('shell', 'dumpsys', 'input_method').decode(errors='replace')
        if re.search(r'\bmInputShown=true\b|\bmIsInputViewShown=true\b', state):
            self.adb('shell', 'input', 'keyevent', 'KEYCODE_BACK')

    def details(self, callsign):
        self.tool('Overlays')
        try:
            select(self.tree(), rid='hierarchy_search')
        except LookupError:
            self.tap(rid='hierarchy_search_btn')
        existing = self.find(rid='hierarchy_search').get('text', '')
        if len(existing) > 80:
            raise ValueError('unexpected hierarchy query length')
        self.tap(rid='hierarchy_search')
        self.adb('shell', 'input', 'keyevent', 'KEYCODE_MOVE_END')
        if existing:
            self.adb('shell', 'input', 'keyevent', *(['KEYCODE_DEL'] * len(existing)))
        self.adb('shell', 'input', 'text', callsign.replace(' ', '%s'))
        self.hide_keyboard()
        self.tap(rid='hierarchy_manager_list_item_title', text=callsign)
        actual = self.find(rid='cotInfoNameEdit').get('text')
        if actual != callsign:
            raise ValueError('wrong marker detail pane')

    def verify_point(self, callsign, lat, lon, evidence):
        if self.find(rid='cotInfoNameEdit').get('text') != callsign:
            raise ValueError('wrong callsign in marker pane')
        self.tap(rid='cotInfoCoordButton')
        self.tap(text='DD')
        actual_lat = float(self.find(rid='coordDialogDDLatText').get('text'))
        actual_lon = float(self.find(rid='coordDialogDDLonText').get('text'))
        if abs(actual_lat-lat) > .0000005 or abs(actual_lon-lon) > .0000005:
            raise ValueError('Android coordinates differ from expected point')
        self.capture(evidence + '-coordinates')
        self.adb('shell', 'input', 'keyevent', 'KEYCODE_BACK')
        self.tap(rid='cotInfoPanButton')
        self.capture(evidence + '-map')

    def rename(self, callsign):
        current = self.find(rid='cotInfoNameEdit').get('text', '')
        if not 1 <= len(current) <= 80 or not re.fullmatch(r'[A-Za-z0-9 -]{1,80}', callsign):
            raise ValueError('unsupported synthetic callsign')
        self.tap(rid='cotInfoNameEdit')
        self.adb('shell', 'input', 'keyevent', 'KEYCODE_MOVE_END')
        self.adb('shell', 'input', 'keyevent', *(['KEYCODE_DEL'] * len(current)))
        self.adb('shell', 'input', 'text', callsign.replace(' ', '%s'))
        # CoTInfoView updates the marker from its text watcher. The name-title
        # icon opens affiliation options, so it is not a focus/commit target.
        self.hide_keyboard()
        if self.find(rid='cotInfoNameEdit').get('text') != callsign:
            raise ValueError('Android callsign edit not visible')
        return int(self.adb('shell', 'date', '+%s').strip())

    def share_dialog(self):
        self.tap(rid='cotInfoSendButton')
        self.find(rid='contact_list_button_send_to_all', text='Broadcast')

    def broadcast(self):
        # Deliberately choose the real all/server Broadcast target, never the
        # silent observer (which has not advertised itself as a contact).
        self.tap(rid='contact_list_button_send_to_all', text='Broadcast')
