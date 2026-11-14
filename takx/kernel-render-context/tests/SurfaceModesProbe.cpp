// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Owned mixed-interface CPU regression; no renderer qualification.
#include <jni.h>
#include <memory>
#include "interop/core/ManagedRenderSurface.h"
using TAKEngineJNI::Interop::Core::ManagedRenderSurface;
extern "C" JNIEXPORT jlongArray JNICALL Java_SurfaceModesProbe_sizes(JNIEnv* env,jclass,jobject legacy,jobject modern,jboolean modernFirst) {
    std::unique_ptr<ManagedRenderSurface> first(new ManagedRenderSurface(*env,modernFirst?modern:legacy));
    if(env->ExceptionCheck())return nullptr;
    std::unique_ptr<ManagedRenderSurface> second(new ManagedRenderSurface(*env,modernFirst?legacy:modern));
    if(env->ExceptionCheck())return nullptr;
    auto* a=modernFirst?second.get():first.get();auto* b=modernFirst?first.get():second.get();
    jlong values[4];values[0]=a->getWidth();if(env->ExceptionCheck())return nullptr;
    values[1]=a->getHeight();if(env->ExceptionCheck())return nullptr;
    values[2]=b->getWidth();if(env->ExceptionCheck())return nullptr;
    values[3]=b->getHeight();if(env->ExceptionCheck())return nullptr;
    jlongArray result=env->NewLongArray(4);if(env->ExceptionCheck())return nullptr;
    env->SetLongArrayRegion(result,0,4,values);return result;
}
