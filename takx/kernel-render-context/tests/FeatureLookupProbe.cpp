// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Owned source-contract/typed JNI CPU control; no renderer qualification.
#include <jni.h>
#include <string>
extern "C" JNIEXPORT void JNICALL Java_FeatureLookupProbe_lookup(JNIEnv* env,jclass,jstring type,jstring name,jstring descriptor,jint kind) {
    auto text=[&](jstring value){const char* raw=env->GetStringUTFChars(value,nullptr);std::string result=raw?raw:"";if(raw)env->ReleaseStringUTFChars(value,raw);return result;};
    std::string cls=text(type),member=text(name),signature=text(descriptor);
    if(env->ExceptionCheck())return;
    jclass target=env->FindClass(cls.c_str());if(env->ExceptionCheck() || !target)return;
    if(kind==0)env->GetFieldID(target,member.c_str(),signature.c_str());
    if(kind==1)env->GetMethodID(target,member.c_str(),signature.c_str());
    if(kind==2)env->GetStaticFieldID(target,member.c_str(),signature.c_str());
    if(kind==3)env->GetStaticMethodID(target,member.c_str(),signature.c_str());
    env->ExceptionCheck();env->DeleteLocalRef(target);
}

#include "common.h"
#include "interop/feature/Interop.h"
using namespace TAK::Engine::Util;
extern "C" JNIEXPORT jlongArray JNICALL Java_FeatureLookupProbe_marshalOptions(JNIEnv* env,jclass,jobject value) {
    TAK::Engine::Renderer::Feature::GLBatchGeometryFeatureDataStoreRenderer3::Options options;
    const auto defaultHints=options.labelHints;
    const auto result=TAKEngineJNI::Interop::Feature::Interop_marshal(options,*env,value);
    if(env->ExceptionCheck())return nullptr;
    if(ATAKMapEngineJNI_checkOrThrow(env,result))return nullptr;
    const jlong rows[]={options.labelsEnabled?1:0,static_cast<jlong>(options.labelHints),
        static_cast<jlong>(options.filter.featureIds->size()),static_cast<jlong>(defaultHints)};
    jlongArray output=env->NewLongArray(4);if(env->ExceptionCheck())return nullptr;
    env->SetLongArrayRegion(output,0,4,rows);if(env->ExceptionCheck())return nullptr;return output;
}
extern "C" JNIEXPORT jobject JNICALL Java_FeatureLookupProbe_envelope(JNIEnv* env,jclass) {
    TAKEngineJNI::Interop::Java::JNILocalRef value(*env,nullptr);
    TAK::Engine::Feature::Envelope2 bounds(1,2,3,4,5,6);
    const auto result=TAKEngineJNI::Interop::Feature::Interop_marshal(value,*env,bounds);
    if(env->ExceptionCheck())return nullptr;
    if(ATAKMapEngineJNI_checkOrThrow(env,result))return nullptr;
    return value.release();
}
