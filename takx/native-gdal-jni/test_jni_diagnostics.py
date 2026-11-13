# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Real diagnostic fixtures; these guards do not load a JVM or grant acceptance."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('jni_diagnostics', Path(__file__).parents[1] / 'jni_diagnostics.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StrictDiagnosticGuards(unittest.TestCase):
    def test_actual_critical_warning_and_mixed_case_variants_rejected(self):
        fixture = ('Warning: Calling other JNI functions in the scope of '
                   'Get/ReleasePrimitiveArrayCritical or Get/ReleaseStringCritical')
        for text in (fixture, fixture.upper(), fixture.lower(), fixture.swapcase()):
            with self.subTest(text=text):
                self.assertEqual(module.strict_jni_failures(text), [text])

    def test_checked_jni_native_local_ref_and_vm_errors_rejected(self):
        fixtures = (
            'WARNING in native method: JNI call made without checking exceptions when required to',
            'warning: jni local refs: 33, exceeds capacity: 32',
            'JNI DETECTED ERROR IN APPLICATION: use of invalid jobject',
            '[warning][jni,resolve] Re-registering JNI native method',
            'FATAL ERROR in native method: Bad global or local ref passed to JNI',
            'A fatal error has been detected by the Java Runtime Environment',
            'java.lang.UnsatisfiedLinkError: unavailable owned symbol',
        )
        for text in fixtures:
            with self.subTest(text=text):
                self.assertEqual(module.strict_jni_failures(text), [text])

    def test_success_marker_never_masks_a_warning(self):
        warning = 'Warning: Calling other JNI functions in the scope of Get/ReleasePrimitiveArrayCritical'
        self.assertEqual(module.strict_jni_failures('PASS_CONTROLS\n' + warning + '\nPASS_MORE'), [warning])

    def test_ordinary_driver_negative_control_and_loader_notes_are_not_jni_warnings(self):
        text = ('ERROR 4: expected missing GDAL input\n'
                'SLF4J: Failed to load class org.slf4j.impl.StaticLoggerBinder\n'
                'PASS_REAL_GDAL_ENUMERATION_PROGRESS_ORIGINAL_THROWABLE_CONTROLS')
        self.assertEqual(module.strict_jni_failures(text), [])


if __name__ == '__main__':
    unittest.main()
