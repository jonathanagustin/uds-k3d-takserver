// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
import gov.tak.platform.datapackage.PackageReader;
import gov.tak.platform.datapackage.content.PackageManifest;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.StringJoiner;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Calls unchanged official production reader/model code, never a replacement parser. */
public final class MissionPackageConformance {
    private static final Map<String,Boolean> checks = new LinkedHashMap<>();
    private static void check(String name, boolean condition) {
        if (!condition) throw new AssertionError(name);
        checks.put(name,true);
    }
    public static void main(String[] arguments) throws Exception {
        Path root=Path.of(arguments[0]);
        PackageManifest manifest;
        try (PackageReader reader=new PackageReader(root.resolve("canonical.zip").toFile())) {
            manifest=reader.getManifest();
            check("actualReaderVersion2",manifest.getVersion()==2);
            check("configurationNameAndUid",manifest.getConfiguration().getName().equals("Synthetic mission package TEST") &&
                  manifest.getConfiguration().getUid().equals("00000000-0000-4000-8000-000000000410"));
            check("receiveFlagsPreserved",manifest.getConfiguration().getParameterValue("onReceiveImport").equals("true") &&
                  manifest.getConfiguration().getParameterValue("onReceiveDelete").equals("false"));
            check("manifestInventory",manifest.getContents().getContents().size()==2 &&
                  manifest.getContents().getContents().get(0).getManifestUid().equals("cot/synthetic-android-mission-point.cot"));
            check("actualZipReaderPayload",reader.readEntryAsString("cot/synthetic-android-mission-point.cot").contains("SYNTHETIC-MISSION TEST"));
            check("cotParameter",manifest.getContents().getContents().get(0).getParameterValue("isCoT").equals("true"));
        }
        manifest.getConfiguration().setParameter("syntheticExtra","retained-value");
        manifest.getContents().getContents().get(1).setIgnore(true);
        String exported=manifest.toXml();
        check("actualSerializerExport",!exported.isBlank());
        try (ZipOutputStream out=new ZipOutputStream(Files.newOutputStream(root.resolve("roundtrip.zip")))) {
            out.putNextEntry(new ZipEntry("MANIFEST/manifest.xml"));
            out.write(exported.getBytes(StandardCharsets.UTF_8));out.closeEntry();
        }
        try (PackageReader reader=new PackageReader(root.resolve("roundtrip.zip").toFile())) {
            PackageManifest roundtrip=reader.getManifest();
            check("actualSerializerReaderRoundTrip",roundtrip.getConfiguration().getParameterValue("syntheticExtra").equals("retained-value") &&
                  roundtrip.getContents().getContents().get(1).isIgnore() && roundtrip.getVersion()==2);
        }
        try (PackageReader reader=new PackageReader(root.resolve("legacy.zip").toFile())) {
            check("actualLegacyRootManifestLocation",reader.getManifest().getVersion()==2);
        }
        try (PackageReader reader=new PackageReader(root.resolve("nested.zip").toFile())) {
            check("nestedManifestUnsupportedByThisTAKXReader",!reader.hasPackageManifest());
        }
        for (String name:new String[]{"missing","malformed"}) {
            try (PackageReader reader=new PackageReader(root.resolve(name+".zip").toFile())) {
                try {reader.getManifest();throw new AssertionError(name+" unexpectedly accepted");}
                catch (IOException expected) {checks.put(name+"ManifestRejected",true);}
            }
        }
        // These characterize actual admission gaps. They are NOT rejection or extraction claims.
        try (PackageReader reader=new PackageReader(root.resolve("traversal.zip").toFile())) {
            check("readerExposesTraversalNameWithoutExtracting",reader.getManifest().getContents().getContents().get(1).getManifestUid().equals("../escape.txt") &&
                  reader.readEntryAsString("../escape.txt").equals("SYNTHETIC TRAVERSAL"));
            check("readerDoesNotWriteOutsidePackage",!Files.exists(root.getParent().resolve("escape.txt")));
        }
        try (PackageReader reader=new PackageReader(root.resolve("duplicate.zip").toFile())) {
            check("duplicateZipEntriesNotRejected",reader.findEntries(entry->entry.getName().equals("files/README.txt")).size()==2);
            check("duplicateZipLookupUsesLastEntry",reader.readEntryAsString("files/README.txt").equals("LAST"));
        }
        try (PackageReader reader=new PackageReader(root.resolve("missing-content.zip").toFile())) {
            check("manifestDoesNotValidateMissingContent",reader.getManifest().getContents().getContents().size()==2 && !reader.hasEntry("files/README.txt"));
        }
        try (PackageReader reader=new PackageReader(root.resolve("size.zip").toFile())) {
            check("readerHasNoFixtureSizeAdmissionCap",reader.readEntry("files/README.txt").length==4097);
        }
        boolean externalResolved=false;
        try (PackageReader reader=new PackageReader(root.resolve("external-dtd.zip").toFile())) {
            externalResolved=reader.getManifest().getConfiguration().getUid().equals("SYNTHETIC-EXTERNAL-DTD");
        } catch (IOException expected) { /* Report the actual pinned JAXB/JDK behavior. */ }
        StringJoiner json=new StringJoiner(",","{\"checks\":{","},\"externalDtdResolved\":"+externalResolved+"}");
        checks.forEach((key,value)->json.add("\""+key+"\":"+value));
        System.out.println(json);
    }
}
