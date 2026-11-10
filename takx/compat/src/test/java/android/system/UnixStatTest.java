// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package android.system;

import java.nio.file.Files;
import java.nio.file.Path;
import java.io.IOException;

/** Expected values come from Python os.stat, independently of Java NIO. */
public final class UnixStatTest {
    private static int checks;
    private static void check(boolean value, String message) {
        checks++; if (!value) throw new AssertionError(message);
    }
    private static void errno(String path, int expected) throws Exception {
        try { Os.stat(path); } catch (ErrnoException error) {
            check(error.errno==expected && error.functionName.equals("stat"),"typed stat errno for " + path);
            check(path.isEmpty() || error.getCause() instanceof IOException,"preserve typed filesystem cause"); return;
        }
        throw new AssertionError("expected errno " + expected);
    }
    private static void providerFailure(String path, int typedErrno) throws Exception {
        try { Os.stat(path); } catch (ErrnoException error) {
            check(error.errno==typedErrno,"only the actual typed provider error is mapped"); return;
        } catch (UnsupportedOperationException error) {
            check(error.getCause() instanceof IOException,"unclassified provider failure retains its cause"); return;
        }
        throw new AssertionError("expected filesystem failure");
    }
    public static void main(String[] args) throws Exception {
        for (String line:Files.readAllLines(Path.of(args[0]))) {
            String[] fields=line.split("\t"); StructStat s=Os.stat(fields[0]);
            long[] actual={s.st_dev,s.st_ino,s.st_rdev,Integer.toUnsignedLong(s.st_uid),Integer.toUnsignedLong(s.st_gid)};
            for(int n=0;n<5;n++) check(actual[n]==Long.parseLong(fields[n+1]),"real Unix field " + n + " for " + fields[0]);
        }
        Path root=Path.of(args[1]);
        errno(root.resolve("missing").toString(),2); errno(root.resolve("dangling").toString(),2); errno("",2);
        providerFailure(root.resolve("file/child").toString(),20);
        providerFailure(root.resolve("loop").toString(),40);
        if(Boolean.parseBoolean(args[2])) errno(root.resolve("denied/child").toString(),13);
        try { Os.stat(null); throw new AssertionError("null path accepted"); } catch (NullPointerException expected) { checks++; }
        check(StructStat.class.getFields().length==5,"only five consumed stat fields are exposed");
        for(java.lang.reflect.Field field:StructStat.class.getFields()) check(java.lang.reflect.Modifier.isFinal(field.getModifiers()),"stat snapshot is immutable");
        System.out.println("Unix stat checks: " + checks);
    }
}
