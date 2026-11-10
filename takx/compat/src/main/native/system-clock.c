// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#define _GNU_SOURCE
#include "android_os_SystemClock.h"
#include <stdint.h>
#include <time.h>

static jlong fail(JNIEnv *env, const char *type, const char *message) {
    jclass exception = (*env)->FindClass(env, type);
    if (exception != NULL) (*env)->ThrowNew(env, exception, message);
    return 0; // A pending Java exception prevents this from being a clock fallback.
}

JNIEXPORT jlong JNICALL Java_android_os_SystemClock_clockMillis(
    JNIEnv *env, jclass type, jboolean include_suspend) {
    (void)type;
    struct timespec value;
    clockid_t clock = include_suspend ? CLOCK_BOOTTIME : CLOCK_MONOTONIC;
    if (clock_gettime(clock, &value) != 0) {
        return fail(env, "java/lang/IllegalStateException", "Linux clock_gettime failed");
    }
    if (value.tv_sec < 0 || value.tv_nsec < 0 || value.tv_nsec >= 1000000000L ||
        value.tv_sec > (INT64_MAX - value.tv_nsec / 1000000L) / 1000) {
        return fail(env, "java/lang/ArithmeticException", "Linux clock value is outside millisecond range");
    }
    return (jlong)value.tv_sec * 1000 + value.tv_nsec / 1000000L;
}
