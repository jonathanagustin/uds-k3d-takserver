# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Pure inventory guards; fixture bytes are not SDK classes or runtime evidence."""
import unittest
import source_families as f


class Families(unittest.TestCase):
    def inputs(self):
        original = {name + '.class': b'original inventory fixture' for name in f.FAMILIES}
        original.update({'gov/tak/platform/commons/opengl/GLES20Constants.class': b'untouched constants',
                         'android/content/res/Resources$Catalog.class': b'original inner fixture',
                         'unrelated/Keep.class': b'untouched unrelated'})
        return original, {name: b'replacement inventory fixture' for name in f.members(original)}

    def test_exact_existing_families_replace_without_duplicates(self):
        original, replacements = self.inputs()
        merged = f.merge(original, replacements)
        self.assertEqual(set(merged), set(original))
        for name in set(original) - set(replacements):
            self.assertEqual(merged[name], original[name])
        self.assertEqual(original['gov/tak/platform/commons/opengl/GLES20.class'], b'original inventory fixture')

    def test_similar_constants_family_is_not_replaceable(self):
        original, replacements = self.inputs()
        replacements['gov/tak/platform/commons/opengl/GLES20Constants.class'] = b'bad scope'
        with self.assertRaises(ValueError):
            f.merge(original, replacements)

    def test_missing_inner_family_member_is_rejected(self):
        original, replacements = self.inputs()
        del replacements['android/content/res/Resources$Catalog.class']
        with self.assertRaises(ValueError):
            f.merge(original, replacements)

    def test_added_class_is_rejected(self):
        original, replacements = self.inputs()
        replacements['new/Unreviewed.class'] = b'bad scope'
        with self.assertRaises(ValueError):
            f.merge(original, replacements)

    def test_required_base_family_cannot_be_omitted(self):
        original, replacements = self.inputs()
        del original['gov/tak/platform/commons/opengl/GLES20.class']
        del replacements['gov/tak/platform/commons/opengl/GLES20.class']
        with self.assertRaises(ValueError):
            f.merge(original, replacements)


if __name__ == '__main__':
    unittest.main()
