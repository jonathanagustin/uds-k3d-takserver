<!-- Copyright 2026 uds-takserver authors -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# ATAK Tools grid regression fixture

`atak-tools-grid.xml` projects the hamburger, complete Tools toolbar and one
Data Packages row from the actual PR #509 failure UI dump. Nodes retain their
captured attributes and nesting; omitted map and grid nodes are unnecessary
for this regression. This is current-loadout overflow, not the complete tool
inventory. It does not contain Import or the All tools & plugins row.

Source evidence: ATAK e2e run `43352887182`, job `131647978889`, artifact
`14006570745`; original ZIP SHA-256
`a9f75fda8dea10d95c0b9e5f185f91008c250217dd7e8417072543a4487513a7`.
The original `scenario/ui/first-failure.xml` SHA-256 is
`f8ba139152dbd47047057002b406e20e47f93abefcc8387767ef0d05d8b09941`.
Tests also construct explicitly synthetic subsequent states from the source
contracts; those states are not observed device acceptance.

The official source revision is `9f6893dd657feacc35ec5de03dad721c2e44170e`.
`NavView` opens current-loadout Tools overflow. `LoadoutToolsDropDown` excludes
visible toolbar tools and appends its settings/pop action last.
`DropDownNavigationStack` appends the close button after those actions.
The settings action returns to the loadout list; its labelled All tools &
plugins row opens a null-loadout Tools inventory containing Import and Overlays.
No fixed coordinates or injected broadcasts are used by the scenario.

The same source audit confirms the browser selection, search, coordinate and
Broadcast resource IDs. `GenericDetailsView` first commits its separate Callsign prompt with Done;
`CoTInfoView` then updates the name through its text watcher;
its name-title icon opens affiliation options and must not be used to commit
an edit. Relevant official source file SHA-256 values:

- `atak/ATAK/app/src/main/java/com/atakmap/android/navigation/views/NavView.java`: `73dff61551342108e385b15592aceb4f3d8c6e25a21ae6edef66f2b347c3f38e`
- `atak/ATAK/app/src/main/java/com/atakmap/android/navigation/views/loadout/LoadoutToolsDropDown.java`: `b7cdbe9757947cb6285b30850cb62265a54fd92c3356fc00344c282fb154ba52`
- `atak/ATAK/app/src/main/java/com/atakmap/android/navigation/views/loadout/LoadoutListDropDown.java`: `cc8e5a1f7524d9ef9915aa90d3c2bf34220c7feb65ab714bd90c8189d7d14227`
- `atak/ATAK/app/src/main/java/com/atakmap/android/navigationstack/DropDownNavigationStack.java`: `fceb61464ba283554347c1c834156d8cd0f4ee47fa3fb868d2b5292ca19c4bf5`
- `atak/ATAK/app/src/main/java/com/atakmap/android/cotdetails/CoTInfoView.java`: `9865fb31a7e4b6d54b862acb9aff08ab1097d0b3e8edf7e9f803c3058ecf7787`
- `atak/ATAK/app/src/main/java/com/atakmap/android/importfiles/ui/ImportManagerView.java`: `c8e2cf815c1259098928cfb96391ffee1ee97a5313376c36e0a211e6cb037adc`
- `atak/ATAK/app/src/main/java/com/atakmap/android/importfiles/ui/ImportManagerFileBrowser.java`: `d91459078394227b697c93178a7a4c296fe0b52739b87aef172bc8b3a2e47b5a`
- `atak/ATAK/app/src/main/java/com/atakmap/android/hierarchy/HierarchyListReceiver.java`: `faeb6d981c26c19ecf744bd37f9d162e50c997562f41c5d651ccc3c0c0a27834`
- `atak/ATAK/app/src/main/java/com/atakmap/android/contact/ContactPresenceDropdown.java`: `4322d0b430443b9a69fc024fdbe089ef9edb81a1d28fa58d18bd2a7f388771e4`
