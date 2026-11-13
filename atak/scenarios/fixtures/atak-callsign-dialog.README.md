# Captured callsign prompt regression

This accessibility hierarchy comes from the failed Android scenario in run
43477896779, job 132066536980, artifact 14064834989. The artifact ZIP digest is
`5f0d2b8c03ee6e5cb86bc962c686a75a2ab7b0254dcd30bb08631651bf9fd583`.
The synthetic challenge suffix is replaced with `00000000`; node structure,
classes, controls and bounds are preserved. Raw screenshots and accessibility
captures remain private.

The run actually passed `stage-and-ui-import`, including the coordinate Cancel
fix, then failed during rename in `android-broadcast-and-fresh-peer-observation`.
It did not qualify broadcast or return verification.

Pinned official revision `9f6893dd657feacc35ec5de03dad721c2e44170e` calls
`GenericDetailsView.addEditTextPrompts` from `CoTInfoView`. The resulting Callsign
dialog has a new input without a resource ID. Its Done button copies the input
back to the original marker field, whose text watcher updates the marker.
Hiding the keyboard does not commit the dialog. The control requires the exact
title, Done and Cancel controls, custom panel, and one enabled input containing
the expected previous synthetic name before editing; it verifies the committed
marker field afterwards.

Official source digests:

- `GenericDetailsView.java`: `605668668c8dd026cacca0ea76a66340d0443ca39699f046734f7678e2aca61e`.
- `CoTInfoView.java`: `9865fb31a7e4b6d54b862acb9aff08ab1097d0b3e8edf7e9f803c3058ecf7787`.
- `CoTInfoBroadcastReceiver.java`: `dc69bd6e12dbc94b02588c53b526ddbcf01ba8dd8b46396a680e8b80c06a1a5c`.
- `ContactPresenceDropdown.java`: `4322d0b430443b9a69fc024fdbe089ef9edb81a1d28fa58d18bd2a7f388771e4`.
- `chat_manager_list_view.xml`: `d427f0a00ba61dc955ca410ae5ed3a3386b91d7b83fda3542676818081a8f7da`.

The remaining source review confirms marker Send selects the contact list, whose
Broadcast button directly sends the marker and closes that list. The reverse
phase reuses the already exercised hierarchy, marker-detail, and coordinate
selectors. A conditional attachment prompt exists when a marker has linked
attachments; it was not reached in this failed run. These source checks and
fixture tests are regression coverage, not acceptance of later device phases.
