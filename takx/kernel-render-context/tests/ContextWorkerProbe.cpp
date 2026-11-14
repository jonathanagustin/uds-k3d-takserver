// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Test instrumentation only: exercises actual Core workers across retirement.
#include <jni.h>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <thread>
#include <chrono>
#include <vector>
#include <cstdio>
#include "core/RenderContext.h"
#include "renderer/GLWorkers.h"
#include "renderer/RenderContextLifecycle.h"
#include "util/Work.h"

using namespace TAK::Engine::Core;
using namespace TAK::Engine::Renderer;
using namespace TAK::Engine::Util;
namespace {
    struct ProbeWork : Work { ProbeWork() NOTHROWS {} };
    struct PendingWork : Work {
        RenderContext* context;
        std::thread::id owner;
        explicit PendingWork(RenderContext* value) : context(value),owner(std::this_thread::get_id()) {}
        TAKErr onSignalWork(TAK::Engine::Thread::MonitorLockPtr& lock) NOTHROWS override {
            lock.reset(nullptr);
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            RenderContext* current=nullptr;
            RenderContext_getCurrent(&current);
            return current==context && owner==std::this_thread::get_id() ? TE_Ok : TE_IllegalState;
        }
    };
    struct Held {
        SharedWorkerPtr resource;
        SharedWorkerPtr thread;
        std::vector<std::shared_ptr<Work>> pending;
    };
    std::map<RenderContext*, Held> held;
    std::mutex heldMutex;
    void fail(JNIEnv* env, const char* message) {
        jclass error = env->FindClass("java/lang/AssertionError");
        if (error) { env->ThrowNew(error, message); env->DeleteLocalRef(error); }
    }
}
extern "C" JNIEXPORT void JNICALL
Java_com_atakmap_map_opengl_ContextWorkerProbe_hold(JNIEnv* env, jclass, jlong raw) {
    auto* context = reinterpret_cast<RenderContext*>(static_cast<intptr_t>(raw));
    if (!context) { fail(env,"Null real context"); return; }
    const bool owning=context->isRenderThread();
    if(env->ExceptionCheck()) return;
    const bool attached=context->isAttached();
    if(env->ExceptionCheck()) return;
    if (!owning || !attached) {
        fail(env, "Probe needs actual owning current context"); return;
    }
    RenderContext_setCurrent(context);
    Held value{GLWorkers_resourceLoad(), GLWorkers_glThread()};
    if (!value.resource || !value.thread) { fail(env, "Missing actual workers"); return; }
    std::lock_guard<std::mutex> lock(heldMutex);
    const auto previous=held.find(context);
    if(previous!=held.end()) for(const auto& worker:{previous->second.resource,previous->second.thread})
        if(worker->scheduleWork(std::make_shared<ProbeWork>())!=TE_Canceled) {
            fail(env,"Held old worker revived after rebind"); return;
        }
    held[context] = std::move(value);
}
extern "C" JNIEXPORT void JNICALL
Java_com_atakmap_map_opengl_ContextWorkerProbe_queuePending(JNIEnv* env,jclass,jlong raw) {
    auto* context=reinterpret_cast<RenderContext*>(static_cast<intptr_t>(raw));
    std::lock_guard<std::mutex> lock(heldMutex);
    const auto found=held.find(context);
    if(found==held.end()) { fail(env,"No live held workers"); return; }
    for(const auto& worker:{found->second.resource,found->second.thread}) for(int i=0;i<256;i++) {
        auto work=std::make_shared<PendingWork>(context);
        if(worker->scheduleWork(work)!=TE_Ok) { fail(env,"Live worker rejected controlled pending work"); return; }
        found->second.pending.push_back(work);
    }
}
extern "C" JNIEXPORT void JNICALL
Java_com_atakmap_map_opengl_ContextWorkerProbe_requireRetired(JNIEnv* env, jclass, jlong raw) {
    auto* context = reinterpret_cast<RenderContext*>(static_cast<intptr_t>(raw));
    std::lock_guard<std::mutex> lock(heldMutex);
    const auto found = held.find(context);
    if (found == held.end()) { fail(env, "No retained workers"); return; }
    for (const auto& worker : {found->second.resource, found->second.thread}) {
        const TAKErr code = worker->scheduleWork(std::make_shared<ProbeWork>());
        if (code != TE_Canceled) { fail(env, "Old worker accepted work after retirement"); return; }
    }
    size_t complete=0,cancelled=0;
    for(const auto& work:found->second.pending) {
        bool done=false; TAKErr result=TE_Err;
        if(work->isDone(done,&result)!=TE_Ok || !done || (result!=TE_Ok && result!=TE_Canceled)) {
            fail(env,"Old Work future was stranded or executed on wrong context/thread"); return;
        }
        if(result==TE_Canceled) ++cancelled; else ++complete;
    }
    if(found->second.pending.size()!=512 || !cancelled) { fail(env,"Pending cancellation branch not exercised"); return; }
    std::printf("WORK_RETIRE completed=%zu cancelled=%zu held_old_rejects=2\n",complete,cancelled);
    std::fflush(stdout);
}
extern "C" JNIEXPORT jlongArray JNICALL
Java_com_atakmap_map_opengl_ContextWorkerProbe_terminalCounts(JNIEnv* env,jclass) {
    size_t active=0,destroyed=0;
    if(RenderContext_terminalCounts(&active,&destroyed)!=TE_Ok) { fail(env,"Lifecycle counts failed"); return nullptr; }
    jlongArray result=env->NewLongArray(2);
    if(!result) return nullptr;
    jlong values[]={static_cast<jlong>(active),static_cast<jlong>(destroyed)};
    env->SetLongArrayRegion(result,0,2,values);
    return result;
}
