// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.system;

/** Actual Unix identity fields consumed by the pinned Kernel VSI handler. */
public final class StructStat {
    public final long st_dev;
    public final long st_ino;
    public final long st_rdev;
    public final int st_uid;
    public final int st_gid;

    StructStat(long dev, long ino, long rdev, int uid, int gid) {
        st_dev = dev;
        st_ino = ino;
        st_rdev = rdev;
        st_uid = uid;
        st_gid = gid;
    }
}
