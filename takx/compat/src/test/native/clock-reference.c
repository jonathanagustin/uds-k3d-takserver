// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#define _GNU_SOURCE
#include <jni.h>
#include <time.h>

JNIEXPORT jlong JNICALL Java_clock_SystemClockCompatibilityTest_reference(
    JNIEnv *env, jclass type, jint identifier) {
    (void)type;
    struct timespec value;
    if (clock_gettime((clockid_t)identifier, &value) != 0) {
        jclass exception = (*env)->FindClass(env, "java/lang/IllegalStateException");
        if (exception != NULL) (*env)->ThrowNew(env, exception, "reference clock_gettime failed");
        return 0;
    }
    return (jlong)value.tv_sec * 1000 + value.tv_nsec / 1000000L;
}
