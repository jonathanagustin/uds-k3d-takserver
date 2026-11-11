// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import com.atakmap.coremap.log.Log;
import com.atakmap.database.DatabaseIface;
import com.atakmap.database.impl.DatabaseImpl;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicInteger;

/** Real unchanged SDK callback API; compares actual baseline and throwing-listener rejection. */
public final class KernelThrowingLoggerCandidate {
    private static final class ControlledLoggerError extends Error {
        ControlledLoggerError() { super("intentional native managed logger callback failure"); }
    }
    private static String wrongKey(Path file) {
        DatabaseIface bad=null;String phase="open";
        try {
            bad=DatabaseImpl.open(file.toString(),"private-proof-wrong-key-0987",DatabaseImpl.OPEN_READONLY);
            if(bad==null)return "null-return";
            phase="read";NativeDatabaseCandidate.verifyRow(bad);
            throw new AssertionError("wrong key unexpectedly read genuine encrypted data");
        } catch(android.database.SQLException expected) {
            for(Throwable t=expected;t!=null;t=t.getCause())
                if(t instanceof Error)throw new AssertionError("logger/linkage/runtime Error must not count as wrong-key rejection",t);
            return phase+"-SQLException";
        } finally {if(bad!=null)bad.close();}
    }
    private static void recover(Path file) {
        DatabaseIface db=DatabaseImpl.open(file.toString(),"private-proof-correct-key-0123",DatabaseImpl.OPEN_READONLY);
        if(db==null)throw new AssertionError("correct key failed after rejected key");
        try {NativeDatabaseCandidate.verifyRow(db);}finally{db.close();}
    }
    public static void run(Path newPrivateDirectory) throws Exception {
        NativeDatabaseCandidate.run(newPrivateDirectory);
        Path file=newPrivateDirectory.resolve("native-database2-encrypted.sqlite").toAbsolutePath();
        String baseline=wrongKey(file);recover(file);
        AtomicInteger count=new AtomicInteger();
        // Real Log.write catches Exception; controlled Error reaches the actual JNI callback.
        Log.LogListener listener=(tag,message,cause)->{
            if("TAKEngineJNI".equals(tag)){count.incrementAndGet();throw new ControlledLoggerError();}
        };
        String observed;
        Log.registerLogListener(listener);
        try {observed=wrongKey(file);recover(file);}finally{Log.unregisterLogListener(listener);}
        if(count.get()==0)throw new AssertionError("real native logger callback not exercised");
        if(!baseline.equals(observed))throw new AssertionError("throwing logger changed wrong-key behavior");
        recover(file);
        System.out.println("LOGGER_CALLBACKS="+count.get()+" BASELINE_WRONG_KEY="+baseline+" LISTENER_WRONG_KEY="+observed);
        System.out.println("PASS_REAL_THROWING_LOGGER_BASELINE_REJECTION_MATCH_AND_CORRECT_KEY_RECOVERY");
    }
}
