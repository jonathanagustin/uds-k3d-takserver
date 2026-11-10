// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Deterministic link-time test fixture, never included in the runtime library.
#define _GNU_SOURCE
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

int __wrap_clock_gettime(clockid_t clock, struct timespec *value) {
    const char *mode = getenv("UDS_CLOCK_TEST_MODE");
    if (mode != NULL && strcmp(mode, "error") == 0) {
        errno = EIO;
        return -1;
    }
    value->tv_sec = mode != NULL && strcmp(mode, "overflow") == 0 ? INT64_MAX :
        (clock == CLOCK_BOOTTIME ? 123456 : 234567);
    value->tv_nsec = 987654321L;
    return 0;
}
