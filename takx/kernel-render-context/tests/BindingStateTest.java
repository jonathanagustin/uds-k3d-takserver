// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package com.atakmap.map.opengl;

import gov.tak.api.engine.map.RenderContext;
import gov.tak.api.engine.map.RenderSurface;
import java.util.ArrayList;
import java.util.List;

/** State-machine unit test only. This does not qualify a GL implementation. */
public final class BindingStateTest {
    private static int assertions;
    private static void check(boolean value) {
        assertions++;
        if (!value) throw new AssertionError(assertions);
    }
    private static void rejects(Runnable action) {
        try { action.run(); throw new AssertionError("accepted illegal transition"); }
        catch (IllegalStateException expected) { assertions++; }
    }
    static final class Context implements RenderContext<RenderSurface> {
        final List<Runnable> queued = new ArrayList<>();
        boolean current = true;
        final Thread owningThread=Thread.currentThread();
        final RenderSurface surface = new RenderSurface() {
            public double getDpi() { return 96; }
            public int getWidth() { return 32; }
            public int getHeight() { return 24; }
            public void addOnSizeChangedListener(OnSizeChangedListener listener) {}
            public void removeOnSizeChangedListener(OnSizeChangedListener listener) {}
        };
        public boolean isRenderThread() { return current && Thread.currentThread()==owningThread; }
        public void queueEvent(Runnable task) { queued.add(task); }
        public void requestRefresh() {}
        public void setFrameRate(float value) {}
        public float getFrameRate() { return 0; }
        public void setContinuousRenderEnabled(boolean value) {}
        public boolean isContinuousRenderEnabled() { return false; }
        public boolean supportsChildContext() { return false; }
        public RenderContext createChildContext() { throw new UnsupportedOperationException(); }
        public void destroyChildContext(RenderContext child) { throw new UnsupportedOperationException(); }
        public boolean isAttached() { return isRenderThread(); }
        public boolean attach() { return current; }
        public boolean detach() { return false; }
        public boolean isMainContext() { return true; }
        public RenderSurface getRenderSurface() { return surface; }
    }
    public static void main(String[] args) {
        Context old = new Context(), replacement = new Context(), other = new Context();
        RenderContextBinding binding = new RenderContextBinding(old, () -> {});
        RenderContextBinding live = new RenderContextBinding(other, () -> {});
        Object stableSurface = binding.getRenderSurface();
        int[] calls = {0};
        rejects(() -> binding.rebind(replacement));
        binding.queueEvent(() -> { calls[0]++; binding.queueEvent(() -> calls[0]++); });
        binding.beginRelease();
        java.util.concurrent.atomic.AtomicReference<Throwable> failure=new java.util.concurrent.atomic.AtomicReference<>();
        Thread external=new Thread(() -> {
            try { rejects(() -> binding.queueEvent(() -> calls[0]++)); }
            catch(Throwable error) { failure.set(error); }
        });
        external.start();
        try { external.join(3000); } catch(InterruptedException error) { throw new AssertionError(error); }
        check(!external.isAlive() && failure.get()==null);
        binding.drain();
        check(calls[0] == 2);
        binding.retire();
        check(!binding.isAttached() && !binding.isRenderThread());
        rejects(() -> binding.queueEvent(() -> calls[0]++));
        for (Runnable envelope : old.queued) envelope.run();
        check(calls[0] == 2);
        check(live.isAttached());
        binding.rebind(replacement);
        check(binding.getRenderSurface() == stableSurface);
        check(binding.isAttached());
        binding.queueEvent(() -> calls[0]++);
        replacement.queued.get(0).run();
        check(calls[0] == 3);
        replacement.current = false;
        rejects(binding::drain);
        check(live.isAttached());
        replacement.current = true;
        binding.beginRelease(); binding.drain(); binding.retire(); binding.terminate();
        rejects(() -> binding.rebind(new Context()));
        rejects(binding::requestRefresh);
        check(!binding.isAttached() && !binding.isRenderThread());
        for (int i=0;i<8;i++) {
            RenderContextBinding fresh = new RenderContextBinding(new Context(), () -> {});
            check(fresh != binding && fresh.isAttached());
            check(live.isAttached());
            rejects(() -> binding.queueEvent(() -> {}));
        }
        System.out.println("binding state assertions=" + assertions);
    }
}
