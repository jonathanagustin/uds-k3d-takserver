// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Owned CPU JNI callback control; not renderer acceptance.
#include <jni.h>
#include "interop/core/ManagedRenderContext.h"
using TAKEngineJNI::Interop::Core::ManagedRenderContext;
using namespace TAK::Engine::Core;
using namespace TAK::Engine::Util;
namespace {
struct Listener : RenderSurface::OnSizeChangedListener {
    void onSizeChanged(const RenderSurface&,std::size_t,std::size_t) NOTHROWS override {}
};
int queuedCalls=0;
void noop(void*) NOTHROWS {queuedCalls++;}
}
extern "C" JNIEXPORT void JNICALL Java_ManagedBridgeProbe_exercise(JNIEnv* env,jclass,jobject object,jint operation) {
    Listener first,second;
    ManagedRenderContext context(*env,object);
    if(env->ExceptionCheck())return;
    auto* surface=context.getRenderSurface();
    if(!surface)return;
    // A genuine native consumer may make consecutive context/surface calls.
    // The bridge itself must check its Java upcalls before the next JNI use.
    if(operation==0) {
        auto require=[&](bool condition,const char* message) {if(!condition && !env->ExceptionCheck()) {
            jclass error=env->FindClass("java/lang/AssertionError");if(error)env->ThrowNew(error,message);
        }};
        require(context.isRenderThread(),"render thread value"); context.requestRefresh();
        require(context.setFrameRate(72)==TE_Ok,"set rate status");
        require(context.getFrameRate()==72,"frame rate round trip");
        context.setContinuousRenderEnabled(false);
        require(!context.isContinuousRenderEnabled(),"continuous round trip");
        require(!context.supportsChildContext(),"unsupported child capability");
        require(context.isAttached() && context.attach() && context.detach() && context.isMainContext(),"context boolean values");
        require(surface->getDpi()==96 && surface->getWidth()==160 && surface->getHeight()==120,"surface values");
        std::unique_ptr<void,void(*)(const void*)> value(new int(1),[](const void* p){delete static_cast<const int*>(p);});
        require(context.queueEvent(noop,std::move(value))==TE_Ok && queuedCalls==1,"native runnable round trip");
        surface->addOnSizeChangedListener(&first);surface->addOnSizeChangedListener(&second);
        surface->removeOnSizeChangedListener(first);surface->removeOnSizeChangedListener(second);
        require(context.surface.listeners.empty(),"listener removal bookkeeping");
        env->ExceptionCheck();return;
    }
    switch(operation) {
    case 1:context.isRenderThread();break;
    case 2:context.requestRefresh();break;
    case 3:context.setFrameRate(60);break;
    case 4:context.getFrameRate();break;
    case 5:context.setContinuousRenderEnabled(true);break;
    case 6:context.isContinuousRenderEnabled();break;
    case 7:context.supportsChildContext();break;
    case 8:context.isAttached();break;
    case 9:context.attach();break;
    case 10:context.detach();break;
    case 11:context.isMainContext();break;
    case 12:surface->getDpi();break;
    case 13:surface->getWidth();break;
    case 14:surface->getHeight();break;
    case 16:{std::unique_ptr<void,void(*)(const void*)> value(new int(1),[](const void* value){delete static_cast<const int*>(value);});context.queueEvent(noop,std::move(value));break;}
    case 17:surface->addOnSizeChangedListener(&first);break;
    case 18:surface->addOnSizeChangedListener(&first);surface->removeOnSizeChangedListener(first);break;
    case 19:surface->addOnSizeChangedListener(&first);surface->addOnSizeChangedListener(&second);surface->getDpi();break;
    case 20:case 21:case 22:case 23:{RenderContextPtr child(nullptr,nullptr);const auto result=context.createChildContext(child);
        if(operation==23 && result!=TE_IllegalState && !env->ExceptionCheck()) {
            jclass error=env->FindClass("java/lang/AssertionError");if(error)env->ThrowNew(error,"Unsupported child accepted");
        }
        break;
    }
    }
    env->ExceptionCheck();
}
