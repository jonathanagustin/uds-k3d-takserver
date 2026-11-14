// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#include <jni.h>
#include <cmath>
#include <cstring>
#include "interop/elevation/ManagedElevationChunk.h"
using TAKEngineJNI::Interop::Elevation::ManagedElevationChunk;
using namespace TAK::Engine::Elevation;
using namespace TAK::Engine::Util;
namespace { int status; }
extern "C" JNIEXPORT jint JNICALL Java_ElevationChunkProbe_status(JNIEnv*,jclass){return status;}
extern "C" JNIEXPORT void JNICALL Java_ElevationChunkProbe_exercise(JNIEnv* env,jclass,jobject object,jint operation) {
    status=0;
    ManagedElevationChunk chunk(env,object);
    if(env->ExceptionCheck()){status=1;return;}
    double value=NAN,lat=.2,lon=.4;
    ElevationChunkDataPtr data(nullptr,nullptr);
    switch(operation){
        case 1:chunk.getResolution();break;
        case 2:chunk.getCE();break;
        case 3:chunk.getLE();break;
        case 4:chunk.isAuthoritative();break;
        case 5:chunk.getFlags();break;
        case 6:chunk.createData(data);break;
        case 7:chunk.sample(&value,lat,lon);break;
        case 8:chunk.sample(&value,1,&lat,&lon,1,1,1);break;
        case 9:return;
        default:
            if(std::strcmp(chunk.getType(),"owned-chunk") || std::strcmp(chunk.getUri(),"memory://owned-chunk") || !chunk.getBounds())return;
            if(chunk.getResolution()!=1 || chunk.getCE()!=2 || chunk.getLE()!=3 || !chunk.isAuthoritative() || chunk.getFlags()!=1)return;
            if(chunk.sample(&value,lat,lon)!=TE_Ok || std::abs(value-50)>1e-10)return;
            value=NAN;
            if(chunk.sample(&value,1,&lat,&lon,1,1,1)!=TE_Ok || std::abs(value-50)>1e-10)return;
            status=2;return;
    }
    if(!env->ExceptionCheck())return;
    // With the primary still pending, every entry guard must refuse further callbacks.
    bool guarded=std::isnan(chunk.getResolution()) && std::isnan(chunk.getCE()) && std::isnan(chunk.getLE()) &&
        !chunk.isAuthoritative() && chunk.getFlags()==0 && chunk.createData(data)==TE_Err &&
        chunk.sample(&value,lat,lon)==TE_Err && chunk.sample(&value,1,&lat,&lon,1,1,1)==TE_Err;
    status=guarded?3:0;
}
