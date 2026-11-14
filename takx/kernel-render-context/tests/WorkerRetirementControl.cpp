// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// CPU-only control of the exact production wrapper with genuine Kernel Work.
#include "RetirableWorkerUnderTest.hpp"
#include <chrono>
#include <cstdio>

struct SlowWork final : Work {
    TAKErr onSignalWork(TAK::Engine::Thread::MonitorLockPtr &lock) NOTHROWS override {
        lock.reset(nullptr);
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
        return TE_Ok;
    }
};
struct PendingWork final : Work {};
struct ErrorWorker final : ControlWorker {
    TAKErr scheduleWork(std::shared_ptr<Work>) NOTHROWS override { return TE_Err; }
    TAKErr doAnyWork(int64_t) NOTHROWS override { return TE_Err; }
    TAKErr doAllWork(int64_t) NOTHROWS override { return TE_Err; }
    TAKErr interrupt() NOTHROWS override { return TE_Ok; }
};
int main() {
    std::shared_ptr<ControlWorker> real;
    if (Worker_createControlWorker(real)!=TE_Ok || !real) return 10;
    RetirableWorker wrapper(real);
    auto slow=std::make_shared<SlowWork>();
    auto pending=std::make_shared<PendingWork>();
    if(wrapper.scheduleWork(slow)!=TE_Ok || wrapper.scheduleWork(pending)!=TE_Ok) return 11;
    if(wrapper.beginRetirement()!=TE_Ok) return 12;
    TAKErr foreign=TE_Ok;
    std::thread submit([&]{foreign=wrapper.scheduleWork(std::make_shared<PendingWork>());});
    submit.join();
    if(foreign!=TE_Canceled) return 13;
    const TAKErr retirement=wrapper.retire();
    bool slowDone=false,pendingDone=false;
    TAKErr slowResult=TE_Err,pendingResult=TE_Err;
    if(slow->isDone(slowDone,&slowResult)!=TE_Ok || !slowDone || slowResult!=TE_Ok) return 14;
    if(pending->isDone(pendingDone,&pendingResult)!=TE_Ok || !pendingDone || pendingResult!=TE_Canceled) return 15;
    if(!wrapper.closed() || wrapper.scheduleWork(std::make_shared<PendingWork>())!=TE_Canceled) return 16;
    RetirableWorker error(std::make_shared<ErrorWorker>());
    if(error.beginRetirement()!=TE_Ok || error.retire()!=TE_Err) return 17;
    std::printf("retirement=%d expected=%d completed=1 canceled=1 foreign_rejected=1 closed=1 error_preserved=1\n",int(retirement),int(TE_Ok));
    return retirement==TE_Ok ? 0 : 18;
}
