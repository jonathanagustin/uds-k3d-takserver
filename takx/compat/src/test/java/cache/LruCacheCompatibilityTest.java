// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package cache;

import android.util.LruCache;
import java.io.Closeable;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;

public final class LruCacheCompatibilityTest {
    private static final AtomicInteger checks = new AtomicInteger();
    private static void check(boolean value) {
        int count = checks.incrementAndGet();
        if (!value) throw new AssertionError("cache check " + count);
    }
    private static void throwsType(Class<? extends Throwable> type, Runnable operation) {
        try { operation.run(); } catch (Throwable error) {
            check(type.isInstance(error));
            return;
        }
        throw new AssertionError("expected " + type.getName());
    }
    private static void await(CountDownLatch latch) {
        try { check(latch.await(5, TimeUnit.SECONDS)); }
        catch (InterruptedException error) { throw new AssertionError(error); }
    }
    private static void join(Thread thread) throws InterruptedException {
        thread.join(5000);
        check(!thread.isAlive());
    }

    private static void orderingAndStats() {
        LruCache<String, String> cache = new LruCache<>(2);
        check(cache.get("missing") == null);
        cache.put("a", "A"); cache.put("b", "B");
        check(cache.get("a").equals("A"));
        cache.put("c", "C");
        check(new ArrayList<>(cache.snapshot().keySet()).equals(Arrays.asList("a", "c")));
        Map<String, String> copy = cache.snapshot(); copy.clear();
        check(cache.size() == 2 && cache.maxSize() == 2);
        check(cache.hitCount() == 1 && cache.missCount() == 1);
        check(cache.putCount() == 3 && cache.createCount() == 0 && cache.evictionCount() == 1);
        check(cache.toString().equals("LruCache[maxSize=2,hits=1,misses=1,hitRate=50%]"));
        cache.resize(1);
        check(cache.snapshot().keySet().equals(java.util.Collections.singleton("c")));
        check(cache.evictionCount() == 2);
        cache.resize(3); check(cache.maxSize() == 3 && cache.size() == 1);
        cache.evictAll(); check(cache.size() == 0 && cache.evictionCount() == 3);
        LruCache<String, String> computed = new LruCache<String, String>(1) {
            @Override protected String create(String key) { check(!Thread.holdsLock(this)); return key.toUpperCase(java.util.Locale.ROOT); }
        };
        check(computed.get("created").equals("CREATED"));
        check(computed.get("created").equals("CREATED"));
        check(computed.createCount() == 1 && computed.hitCount() == 1 && computed.missCount() == 1);
    }

    private static void invalidAndWeighted() {
        throwsType(IllegalArgumentException.class, () -> new LruCache<>(0));
        throwsType(IllegalArgumentException.class, () -> new LruCache<>(-1));
        LruCache<String, String> cache = new LruCache<>(2);
        throwsType(NullPointerException.class, () -> cache.get(null));
        throwsType(NullPointerException.class, () -> cache.put(null, "v"));
        throwsType(NullPointerException.class, () -> cache.put("k", null));
        throwsType(NullPointerException.class, () -> cache.remove(null));
        throwsType(IllegalArgumentException.class, () -> cache.resize(0));
        check(cache.maxSize() == 2);
        LruCache<String, String> weighted = new LruCache<String, String>(5) {
            @Override protected int sizeOf(String key, String value) { return value.length(); }
        };
        weighted.put("a", "123"); weighted.put("b", "12");
        check(weighted.size() == 5);
        weighted.put("a", "1"); check(weighted.size() == 3);
        weighted.put("large", "123456"); check(weighted.size() == 0);
        LruCache<String, String> negative = new LruCache<String, String>(2) {
            @Override protected int sizeOf(String key, String value) { return -1; }
        };
        throwsType(IllegalStateException.class, () -> negative.put("a", "A"));
        LruCache<String, int[]> mutable = new LruCache<String, int[]>(2) {
            @Override protected int sizeOf(String key, int[] value) { return value[0]; }
        };
        int[] value = {1}; mutable.put("a", value); value[0] = 2;
        throwsType(IllegalStateException.class, () -> mutable.trimToSize(0));
        LruCache<String, String> zero = new LruCache<String, String>(1) {
            @Override protected int sizeOf(String key, String value) { return 0; }
        };
        zero.put("a", "A"); zero.trimToSize(0); check(zero.snapshot().size() == 1);
        zero.evictAll(); check(zero.snapshot().isEmpty() && zero.evictionCount() == 1);
    }

    private static final class Resource implements Closeable {
        final Path path;
        final FileChannel channel;
        int closes;
        Resource() throws IOException {
            path = Files.createTempFile("takx-lru-resource-", ".bin");
            channel = FileChannel.open(path, StandardOpenOption.READ, StandardOpenOption.WRITE);
        }
        @Override public void close() {
            closes++;
            try { channel.close(); Files.delete(path); }
            catch (IOException error) { throw new AssertionError(error); }
        }
    }
    private static class ResourceCache extends LruCache<String, Resource> {
        final ArrayList<Boolean> evictions = new ArrayList<>();
        ResourceCache(int maximum) { super(maximum); }
        @Override protected void entryRemoved(boolean evicted, String key, Resource old, Resource replacement) {
            check(!Thread.holdsLock(this));
            evictions.add(evicted);
            old.close();
        }
    }
    private static void resourceLifetime() throws IOException {
        ResourceCache cache = new ResourceCache(32);
        Resource first = new Resource(), replacement = new Resource();
        cache.put("same", first); cache.put("same", replacement);
        check(first.closes == 1 && !first.channel.isOpen() && replacement.channel.isOpen());
        check(cache.evictions.equals(Arrays.asList(false)));
        ArrayList<Resource> resources = new ArrayList<>();
        for (int i = 0; i < 32; i++) {
            Resource item = new Resource(); resources.add(item); cache.put("tile-" + i, item);
        }
        check(replacement.closes == 1 && cache.size() == 32 && cache.evictionCount() == 1);
        Resource removed = cache.remove("tile-0");
        check(removed == resources.get(0) && removed.closes == 1 && !removed.channel.isOpen());
        cache.resize(2); check(cache.size() == 2);
        cache.evictAll();
        for (Resource resource : resources) check(resource.closes == 1 && !resource.channel.isOpen());
        check(cache.remove("absent") == null);
    }

    private static void createRaceAndCallbacks() throws Exception {
        CountDownLatch creating = new CountDownLatch(1), finish = new CountDownLatch(1);
        Resource created = new Resource(), winner = new Resource();
        AtomicReference<Throwable> error = new AtomicReference<>();
        AtomicReference<Resource> result = new AtomicReference<>();
        ResourceCache cache = new ResourceCache(1) {
            @Override protected Resource create(String key) {
                check(!Thread.holdsLock(this));
                creating.countDown(); await(finish); return created;
            }
        };
        Thread thread = new Thread(() -> {
            try { result.set(cache.get("tile")); } catch (Throwable failure) { error.set(failure); }
        });
        thread.start(); await(creating); cache.put("tile", winner); finish.countDown(); join(thread);
        check(error.get() == null && result.get() == winner);
        check(created.closes == 1 && !created.channel.isOpen() && winner.channel.isOpen());
        check(cache.createCount() == 1 && cache.missCount() == 1 && cache.putCount() == 1);
        check(cache.evictionCount() == 0 && cache.evictions.equals(Arrays.asList(false)));
        cache.remove("tile"); check(winner.closes == 1);

        CountDownLatch bothCreating = new CountDownLatch(2), letBothFinish = new CountDownLatch(1);
        Resource left = new Resource(), right = new Resource();
        ResourceCache racing = new ResourceCache(1) {
            @Override protected Resource create(String key) {
                check(!Thread.holdsLock(this));
                Resource resource = Thread.currentThread().getName().equals("left") ? left : right;
                bothCreating.countDown(); await(letBothFinish); return resource;
            }
        };
        AtomicReference<Resource> leftResult = new AtomicReference<>(), rightResult = new AtomicReference<>();
        Thread leftThread = new Thread(() -> {
            try { leftResult.set(racing.get("tile")); } catch (Throwable failure) { error.set(failure); }
        }, "left");
        Thread rightThread = new Thread(() -> {
            try { rightResult.set(racing.get("tile")); } catch (Throwable failure) { error.set(failure); }
        }, "right");
        leftThread.start(); rightThread.start(); await(bothCreating); letBothFinish.countDown();
        join(leftThread); join(rightThread);
        check(error.get() == null && leftResult.get() == rightResult.get());
        check(left.closes + right.closes == 1 && leftResult.get().channel.isOpen());
        check(racing.createCount() == 2 && racing.missCount() == 2 && racing.putCount() == 0);
        racing.evictAll(); check(left.closes == 1 && right.closes == 1);

        CountDownLatch callback = new CountDownLatch(1), release = new CountDownLatch(1);
        LruCache<String, String> reentrant = new LruCache<String, String>(1) {
            @Override protected void entryRemoved(boolean evicted, String key, String old, String next) {
                check(!Thread.holdsLock(this)); callback.countDown(); await(release);
            }
        };
        reentrant.put("old", "old");
        Thread evictor = new Thread(() -> {
            try { reentrant.put("new", "new"); } catch (Throwable failure) { error.set(failure); }
        });
        evictor.start(); await(callback);
        check(reentrant.get("new").equals("new")); // Callback must not hold the cache monitor.
        release.countDown(); join(evictor); check(error.get() == null);
    }

    public static void main(String[] args) throws Exception {
        orderingAndStats(); invalidAndWeighted(); resourceLifetime(); createRaceAndCallbacks();
        System.out.println("PASS LruCache compatibility and real file-channel lifetime: " + checks + " checks");
    }
}
