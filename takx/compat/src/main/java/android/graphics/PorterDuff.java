// SPDX-License-Identifier: GPL-3.0-only
package android.graphics;

/** Blend-mode values used by Kernel's bidirectional marshaling registry.
 * This class does not expose or claim a Canvas/compositing implementation.
 */
public final class PorterDuff {
    private PorterDuff() {}
    public enum Mode {
        CLEAR, SRC, DST, SRC_OVER, DST_OVER, SRC_IN, DST_IN,
        SRC_OUT, DST_OUT, SRC_ATOP, DST_ATOP, XOR, DARKEN,
        LIGHTEN, MULTIPLY, SCREEN, ADD, OVERLAY
    }
}
