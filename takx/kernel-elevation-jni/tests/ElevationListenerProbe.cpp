// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#include <jni.h>
#include "interop/elevation/ManagedElevationSource.h"
using TAKEngineJNI::Interop::Elevation::ManagedElevationSource;
using namespace TAK::Engine::Elevation;
using namespace TAK::Engine::Util;
namespace {
struct Listener final : ElevationSource::OnContentChangedListener {
    int calls=0;
    TAKErr onContentChanged(const ElevationSource&) NOTHROWS override {++calls;return TE_Ok;}
};
void require(JNIEnv* env,bool value,const char* message) {
    if(value||env->ExceptionCheck())return;
    jclass error=env->FindClass("java/lang/AssertionError");
    if(error){env->ThrowNew(error,message);env->DeleteLocalRef(error);}
}
}
extern "C" JNIEXPORT jint JNICALL Java_ElevationListenerProbe_exercise(JNIEnv* env,jclass,jobject object,jint operation) {
    Listener first,second; // Both outlive the managed source and its cleanup.
    ManagedElevationSource source(env,object);
    if(env->ExceptionCheck())return 0;
    if(operation==5)return 0;
    auto result=source.addOnContentChangedListener(&first);
    if(env->ExceptionCheck())return 0;
    require(env,result==TE_Ok,"first listener registration failed");
    result=source.addOnContentChangedListener(&second);
    if(env->ExceptionCheck())return 0;
    require(env,result==TE_Ok&&source.listeners.size()==2,"second listener registration failed");
    if(env->ExceptionCheck())return 0;
    if(operation==1||operation==4)return 0; // Destructor exercises cleanup.
    if(operation==3){source.getBounds();return 0;}
    if(operation==2){source.removeOnContentChangedListener(&first);return 0;}
    const auto bounds=source.getBounds();
    if(env->ExceptionCheck())return 0;
    require(env,bounds.minX==-1&&bounds.minY==-2&&bounds.maxX==3&&bounds.maxY==4,"bounds transfer differs");
    jclass clazz=env->GetObjectClass(object);
    jmethodID fire=env->GetMethodID(clazz,"fire","()V");
    if(!fire||env->ExceptionCheck()){env->DeleteLocalRef(clazz);return 0;}
    env->CallVoidMethod(object,fire);
    const bool failed=env->ExceptionCheck();env->DeleteLocalRef(clazz);
    if(failed)return 0;
    require(env,first.calls==1&&second.calls==1,"native notifications not delivered");
    source.removeOnContentChangedListener(&first);
    if(env->ExceptionCheck())return 0;
    require(env,source.listeners.size()==1,"native listener removal bookkeeping differs");
    return first.calls+second.calls;
}
