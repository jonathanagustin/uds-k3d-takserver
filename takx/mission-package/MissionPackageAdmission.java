// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import gov.tak.platform.datapackage.PackageReader;
import gov.tak.platform.datapackage.ZipReader;
import gov.tak.platform.datapackage.content.PackageManifest;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.StringJoiner;
import java.util.zip.ZipEntry;
import java.util.concurrent.Executors;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipOutputStream;

/** Exercises the actual projected production guards and shared remote admission method. */
public final class MissionPackageAdmission {
    private static final Map<String,Boolean> checks=new LinkedHashMap<>();
    private static void check(String name,boolean condition) {
        if (!condition) throw new AssertionError(name);
        checks.put(name,true);
    }
    private static void rejected(Path path,String name) throws Exception {
        try (PackageReader reader=new PackageReader(path.toFile())) {
            reader.getManifest();
            throw new AssertionError(name+" accepted");
        } catch (IOException expected) {checks.put(name,true);}
    }
    private static String sha(Path path) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
    }
    private static void extractionControls(Path root, Path canonical) throws Exception {
        Path cache=root.resolve("extraction-cache");
        Path same=root.resolve("same-basename.zip");
        File first=PackageReader.extractPackageFile(same.toFile(),"one/README.txt",cache.toFile());
        File second=PackageReader.extractPackageFile(same.toFile(),"two/README.txt",cache.toFile());
        check("exactEntryIdentitySeparatesSameBasename",first.getName().equals("README.txt") && second.getName().equals("README.txt") &&
                !first.toPath().equals(second.toPath()) && Files.readString(first.toPath()).equals("FIRST") && Files.readString(second.toPath()).equals("SECOND"));
        File repeat=PackageReader.extractPackageFile(same.toFile(),"one/README.txt",cache.toFile());
        check("identicalExtractionReusesVerifiedBytes",Files.isSameFile(first.toPath(),repeat.toPath()));
        Path live=root.resolve("live-package.zip");Files.copy(canonical,live);
        File before=PackageReader.extractPackageFile(live.toFile(),"files/README.txt",cache.toFile());
        String original=Files.readString(before.toPath());
        Files.copy(root.resolve("changed-archive.zip"),live,java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        File after=PackageReader.extractPackageFile(live.toFile(),"files/README.txt",cache.toFile());
        check("actualArchiveIdentityInvalidatesStaleCache",!before.equals(after) && Files.readString(before.toPath()).equals(original) && Files.readString(after.toPath()).equals("NEXT"));
        Path legacy=cache.resolve("same-basename/README.txt");Files.createDirectories(legacy.getParent());Files.writeString(legacy,"LEGACY UNTOUCHED");
        PackageReader.extractPackageFile(same.toFile(),"one/README.txt",cache.toFile());
        check("legacyFlatCacheNeverReusedOrOverwritten",Files.readString(legacy).equals("LEGACY UNTOUCHED"));
        Files.writeString(first.toPath(),"CORRUPTED CACHE");
        try {PackageReader.extractPackageFile(same.toFile(),"one/README.txt",cache.toFile());throw new AssertionError("cache collision accepted");}
        catch (IOException expected) {check("cacheCollisionRefusedWithoutOverwrite",Files.readString(first.toPath()).equals("CORRUPTED CACHE"));}
        Path failed=root.resolve("failed-cache");
        try {PackageReader.extractPackageFile(root.resolve("crc.zip").toFile(),"files/README.txt",failed.toFile());throw new AssertionError("CRC extraction accepted");}
        catch (IOException expected) {
            try (var walk=Files.walk(failed)) {check("failedStagingHasNoPublishedFile",walk.noneMatch(Files::isRegularFile));}
        }
        Path outside=root.resolve("outside-cache");Files.createDirectory(outside);
        Path link=root.resolve("linked-cache");Files.createSymbolicLink(link,outside);
        try {PackageReader.extractPackageFile(canonical.toFile(),"files/README.txt",link.toFile());throw new AssertionError("symlink directory accepted");}
        catch (IOException expected) {
            try (var list=Files.list(outside)) {check("symlinkDirectoryRefusedWithoutOutsideWrite",list.findAny().isEmpty());}
        }
        Path symlinkCache=root.resolve("symlink-target-cache");
        File target=PackageReader.extractPackageFile(canonical.toFile(),"files/README.txt",symlinkCache.toFile());
        Path external=root.resolve("owned-external-marker");Files.writeString(external,"SYNTHETIC EXTERNAL");
        Files.delete(target.toPath());Files.createSymbolicLink(target.toPath(),external);
        try {PackageReader.extractPackageFile(canonical.toFile(),"files/README.txt",symlinkCache.toFile());throw new AssertionError("symlink target accepted");}
        catch (IOException expected) {check("symlinkCacheFileRefused",Files.isSymbolicLink(target.toPath()) && Files.readString(external).equals("SYNTHETIC EXTERNAL"));}
        Path unsafe=root.resolve("unsafe-cache");
        try {PackageReader.extractPackageFile(canonical.toFile(),"../escape.txt",unsafe.toFile());throw new AssertionError("unsafe extraction accepted");}
        catch (IOException expected) {check("unsafeExtractionRefusedBeforeStaging",!Files.exists(unsafe));}
        Path concurrent=root.resolve("concurrent-cache");
        var executor=Executors.newFixedThreadPool(2);CountDownLatch start=new CountDownLatch(1);
        try {
            var one=executor.submit(()->{start.await();return PackageReader.extractPackageFile(canonical.toFile(),"files/README.txt",concurrent.toFile());});
            var two=executor.submit(()->{start.await();return PackageReader.extractPackageFile(canonical.toFile(),"files/README.txt",concurrent.toFile());});
            start.countDown();
            File a=one.get(5,TimeUnit.SECONDS),b=two.get(5,TimeUnit.SECONDS);
            check("exclusiveAtomicPublicationHandlesConcurrentIdenticalBytes",Files.isSameFile(a.toPath(),b.toPath()));
        } finally {executor.shutdownNow();}
        try (var walk=Files.walk(cache)) {check("ownedTemporaryStagesCleaned",walk.noneMatch(path->path.getFileName().toString().endsWith(".part")));}
    }

    public static void main(String[] arguments) throws Exception {
        Path root=Path.of(arguments[0]);
        Path canonical=root.resolve("canonical.zip");
        try (PackageReader reader=new PackageReader(canonical.toFile())) {
            PackageManifest manifest=reader.getManifest();
            check("actualPatchedReaderAcceptsCanonical",manifest.getVersion()==2 && manifest.getContents().getContents().size()==2);
            check("parametersPreserved",manifest.getConfiguration().getParameterValue("onReceiveImport").equals("true"));
            manifest.getConfiguration().setParameter("syntheticExtra","preserved");
            manifest.getContents().getContents().get(1).setIgnore(true);
            try (ZipOutputStream out=new ZipOutputStream(Files.newOutputStream(root.resolve("patched-roundtrip.zip")))) {
                out.putNextEntry(new ZipEntry("MANIFEST/manifest.xml"));out.write(manifest.toXml().getBytes(java.nio.charset.StandardCharsets.UTF_8));out.closeEntry();
                String cot="cot/synthetic-android-mission-point.cot";
                out.putNextEntry(new ZipEntry(cot));out.write(reader.readEntry(cot));out.closeEntry();
            }
        }
        try (PackageReader reader=new PackageReader(root.resolve("patched-roundtrip.zip").toFile())) {
            PackageManifest result=reader.getManifest();
            check("serializerAndIgnoredMissingContentPreserved",result.getContents().getContents().get(1).isIgnore() &&
                    result.getConfiguration().getParameterValue("syntheticExtra").equals("preserved"));
        }
        try (PackageReader reader=new PackageReader(root.resolve("directories.zip").toFile())) {
            check("validDirectoryRecordsPreserved",reader.getManifest().getContents().getContents().size()==2);
        }
        try (PackageReader reader=new PackageReader(root.resolve("legacy.zip").toFile())) {
            check("legacyRootManifestPreserved",reader.getManifest().getVersion()==2);
        }
        for (String name:new String[]{"traversal","manifest-traversal","duplicate","missing-content","malformed","missing","nested",
                "backslash","absolute","drive","dot-segment","empty-segment","file-directory-conflict","duplicate-reference",
                "manifest-limit","entry-limit","aggregate-limit","count-limit","external-dtd","internal-dtd","ambiguous"})
            rejected(root.resolve(name+".zip"),name+"Rejected");
        try (PackageReader reader=new PackageReader(root.resolve("crc.zip").toFile())) {
            try (InputStream content=reader.getInputStream("files/README.txt")) {
                content.readAllBytes();throw new AssertionError("CRC mismatch accepted");
            } catch (IOException expected) {checks.put("actualBoundedStreamRejectsCRC",true);}
        }
        File declaredLarge=new File(canonical.toString()) {
            @Override public long length() {return ZipReader.MAX_ARCHIVE_BYTES+1;}
        };
        try (PackageReader ignored=new PackageReader(declaredLarge)) {throw new AssertionError("archive size accepted");}
        catch (IOException expected) {checks.put("archiveLimitBeforeOpening",true);}
        PackageReader.validateReceivedPackage(canonical.toFile(),sha(canonical));
        PackageReader.validateReceivedPackage(canonical.toFile(),sha(canonical).toUpperCase(java.util.Locale.ROOT));
        checks.put("actualSharedRemoteHashAndAdmissionAcceptCanonical",true);
        for (String hash:new String[]{"", "bad", "0".repeat(64)}) {
            try {PackageReader.validateReceivedPackage(canonical.toFile(),hash);throw new AssertionError("invalid hash accepted");}
            catch (IOException expected) {checks.put("invalidRemoteHash"+hash.length()+"Rejected",true);}
        }
        try {PackageReader.validateReceivedPackage(canonical.toFile(),null);throw new AssertionError("missing hash accepted");}
        catch (IOException expected) {checks.put("missingRemoteHashRejected",true);}
        for (String name:new String[]{"traversal","missing-content","crc","crc-extra"}) {
            Path unsafe=root.resolve(name+".zip");
            try {PackageReader.validateReceivedPackage(unsafe.toFile(),sha(unsafe));throw new AssertionError("unsafe valid-hash package accepted");}
            catch (IOException expected) {checks.put(name+"RejectedEvenWithMatchingTransferHash",true);}
        }
        File unreadable=new File(canonical.toString()) {
            @Override public Path toPath() {return root.resolve("does-not-exist");}
        };
        try {PackageReader.validateReceivedPackage(unreadable,sha(canonical));throw new AssertionError("read error accepted");}
        catch (IOException expected) {checks.put("remoteReadErrorRejected",true);}
        extractionControls(root,canonical);
        StringJoiner json=new StringJoiner(",","{\"checks\":{","}}");
        checks.forEach((name,value)->json.add("\""+name+"\":"+value));
        System.out.println(json);
    }
}
