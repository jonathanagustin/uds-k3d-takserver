// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package context;

import android.content.Context;
import android.content.res.AssetManager;
import android.content.res.Resources;
import android.content.pm.PackageManager;
import android.net.Uri;
import java.io.IOException;
import java.io.InputStream;
import java.io.FileNotFoundException;
import java.io.UncheckedIOException;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.jar.JarEntry;
import java.util.jar.JarOutputStream;

public final class ContextIoTest {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("Context IO check " + checks); }
    private interface Action { void run() throws Exception; }
    private static void fails(Class<? extends Throwable> type,Action run) throws Exception {
        try { run.run(); } catch(Throwable failure) { check(type.isInstance(failure)); return; }
        throw new AssertionError("expected "+type.getName());
    }
    private static String text(InputStream input) throws IOException {
        try(InputStream owned=input) { return new String(owned.readAllBytes(),StandardCharsets.UTF_8); }
    }
    private static void write(Path root,String relative,String data) throws IOException {
        Path path=root.resolve(relative);Files.createDirectories(path.getParent());Files.writeString(path,data);
    }
    private static void filesystem(Path work) throws Exception {
        Path cp=work.resolve("cp");Files.createDirectories(cp);
        write(cp,Resources.CATALOG,"test.app/raw/own=res/own.bin\nother.app/raw/other=res/other.bin\ntest.app/string/name=res/name.txt\n");
        write(cp,"res/own.bin","owned");write(cp,"res/other.bin","other");write(cp,"res/name.txt","Name");
        write(cp,"assets/maps/a.txt","A");write(cp,"assets/maps/nested/b.txt","B");write(cp,"assets/with space.txt","space");write(cp,"assets/地图.txt","unicode");
        try(URLClassLoader loader=new URLClassLoader(new URL[]{cp.toUri().toURL()},null)) {
            Context context=new Context(work.resolve("app"),"test.app",loader);
            Path database=context.getDatabasePath("catalog.sqlite").toPath();
            check(database.equals(work.resolve("app/databases/catalog.sqlite")) && !Files.exists(database));
            Files.writeString(database,"database path fixture");
            check(Files.readString(context.getDatabasePath("catalog.sqlite").toPath()).equals("database path fixture"));
            for(String name:new String[]{"../outside","/absolute","a/b","a\\b","..",""})
                fails(IllegalArgumentException.class,()->context.getDatabasePath(name));
            Path outside=work.resolve("outside");Files.writeString(outside,"outside");
            Files.createSymbolicLink(database.getParent().resolve("escaped"),outside);
            fails(UncheckedIOException.class,()->context.getDatabasePath("escaped"));
            Files.delete(database.getParent().resolve("escaped"));Files.delete(database);
            Files.delete(database.getParent());
            Files.createSymbolicLink(work.resolve("app/databases"),cp);
            fails(UncheckedIOException.class,()->context.getDatabasePath("other.sqlite"));
            Files.delete(work.resolve("app/databases"));

            var info=context.getPackageManager().getApplicationInfo("test.app",0);
            check(Files.isDirectory(Path.of(info.nativeLibraryDir)) && info.packageName.equals("test.app"));
            info.nativeLibraryDir="imaginary";
            check(!context.getPackageManager().getApplicationInfo("test.app",0).nativeLibraryDir.equals("imaginary"));
            fails(PackageManager.NameNotFoundException.class,()->context.getPackageManager().getApplicationInfo("unknown",0));
            fails(UnsupportedOperationException.class,()->context.getPackageManager().getApplicationInfo("test.app",1));
            var resolver=context.getContentResolver();
            check(text(resolver.openInputStream(Uri.parse("android.resource://test.app/raw/own"))).equals("owned"));
            int id=context.getResources().getIdentifier("own","raw","test.app");
            check(text(resolver.openInputStream(Uri.parse("android.resource://test.app/"+id))).equals("owned"));
            check(text(resolver.openInputStream(Uri.parse("android.resource://other.app/raw/other"))).equals("other"));
            for(String uri:new String[]{"android.resource://other.app/"+id,"android.resource://unknown/raw/own",
                    "android.resource://test.app/string/name","android.resource://test.app/raw/missing",
                    "android.resource://test.app/raw/../own","android.resource://test.app/9999999999999999",
                    "content://unknown/provider","file://remote/thing","android.resource://test.app/raw/own?x=1"})
                fails(FileNotFoundException.class,()->resolver.openInputStream(Uri.parse(uri)));
            fails(FileNotFoundException.class,()->resolver.openInputStream(Uri.fromFile(cp.toFile())));
            Path local=work.resolve("file with space.txt");Files.writeString(local,"file bytes");
            check(text(resolver.openInputStream(Uri.fromFile(local.toFile()))).equals("file bytes"));
            InputStream stream=resolver.openInputStream(Uri.fromFile(local.toFile()));
            check(stream.read()=='f');stream.close();fails(IOException.class,stream::read);
            AssetManager assets=context.getAssets();
            check(Arrays.equals(assets.list(""),new String[]{"maps","with space.txt","地图.txt"}));
            check(Arrays.equals(assets.list("maps"),new String[]{"a.txt","nested"}));
            check(assets.list("absent").length==0 && assets.list("maps/a.txt").length==0);
            check(text(assets.open("with space.txt")).equals("space"));
            check(text(assets.open("地图.txt")).equals("unicode"));
            for(String path:new String[]{"../res/own.bin","/maps","maps/../a.txt","maps//a.txt","maps\\a.txt"}) {
                fails(IllegalArgumentException.class,()->assets.open(path));
                fails(IllegalArgumentException.class,()->assets.list(path));
            }
            Files.createSymbolicLink(cp.resolve("assets/escape"),outside);
            fails(IOException.class,()->assets.open("escape"));
            fails(IOException.class,()->assets.list(""));
            Files.delete(cp.resolve("assets/escape"));
            Files.createSymbolicLink(cp.resolve("assets/maps/escape-directory"),work);
            fails(IOException.class,()->assets.list("maps/escape-directory"));
            Files.delete(cp.resolve("assets/maps/escape-directory"));
            Path assetRoot=cp.resolve("assets");Path movedRoot=cp.resolve("safe-assets");
            Files.move(assetRoot,movedRoot);Files.createSymbolicLink(assetRoot,work);
            fails(IOException.class,()->assets.list(""));
            Files.delete(assetRoot);Files.move(movedRoot,assetRoot);

            Files.delete(cp.resolve("res/own.bin"));Files.createSymbolicLink(cp.resolve("res/own.bin"),outside);
            fails(FileNotFoundException.class,()->resolver.openInputStream(Uri.parse("android.resource://test.app/raw/own")));
        }
        Path library=work.resolve("native");Files.createDirectories(library);
        String original=System.getProperty("uds.desktop.nativeLibraryPath");
        try {
            System.setProperty("uds.desktop.nativeLibraryPath",library.toString());
            Context configured=new Context(work.resolve("configured"),"test.app",ContextIoTest.class.getClassLoader());
            check(configured.getPackageManager().getApplicationInfo("test.app",0).nativeLibraryDir.equals(library.toString()));
            System.setProperty("uds.desktop.nativeLibraryPath",work.resolve("missing-library").toString());
            fails(UncheckedIOException.class,()->new Context(work.resolve("missing"),"test.app",ContextIoTest.class.getClassLoader()));
        } finally { if(original==null)System.clearProperty("uds.desktop.nativeLibraryPath");else System.setProperty("uds.desktop.nativeLibraryPath",original); }
    }
    private static void jars(Path work) throws Exception {
        Path jar=work.resolve("assets.jar");
        try(JarOutputStream output=new JarOutputStream(Files.newOutputStream(jar))) {
            for(String name:new String[]{"assets/maps/a.txt","assets/maps/nested/b.txt","assets/root.txt","assets/space name.txt"}) {
                output.putNextEntry(new JarEntry(name));output.write(name.getBytes(StandardCharsets.UTF_8));output.closeEntry();
            }
            output.putNextEntry(new JarEntry(Resources.CATALOG));
            output.write("test.app/raw/jar=res/payload.bin\n".getBytes(StandardCharsets.UTF_8));output.closeEntry();
            output.putNextEntry(new JarEntry("res/payload.bin"));output.write("JAR raw".getBytes(StandardCharsets.UTF_8));output.closeEntry();
        } // Intentionally no directory entries.
        try(URLClassLoader loader=new URLClassLoader(new URL[]{jar.toUri().toURL()},null)) {
            AssetManager assets=new AssetManager(loader);
            Context context=new Context(work.resolve("jar-app"),"test.app",loader);
            InputStream raw=context.getContentResolver().openInputStream(Uri.parse("android.resource://test.app/raw/jar"));
            check(raw.read()=='J');raw.close();fails(IOException.class,raw::read);
            check(text(context.getContentResolver().openInputStream(Uri.parse("android.resource://test.app/raw/jar"))).equals("JAR raw"));

            check(Arrays.equals(assets.list(""),new String[]{"maps","root.txt","space name.txt"}));
            check(Arrays.equals(assets.list("maps"),new String[]{"a.txt","nested"}));
            check(Arrays.equals(assets.list("maps/nested"),new String[]{"b.txt"}));
            check(assets.list("missing").length==0);
            check(text(assets.open("space name.txt")).equals("assets/space name.txt"));
            InputStream first=assets.open("maps/a.txt"),second=assets.open("root.txt");
            check(first.read()=='a');first.close();fails(IOException.class,first::read);
            check(text(second).equals("assets/root.txt"));
        }
        try(URLClassLoader loader=new URLClassLoader(new URL[]{work.resolve("cp").toUri().toURL(),jar.toUri().toURL()},null)) {
            check(Arrays.equals(new AssetManager(loader).list(""),new String[]{"maps","root.txt","space name.txt","with space.txt","地图.txt"}));
        }
        Path bad=work.resolve("bad.jar");
        try(JarOutputStream output=new JarOutputStream(Files.newOutputStream(bad))) {
            output.putNextEntry(new JarEntry("assets/../outside"));output.write(1);output.closeEntry();
        }
        try(URLClassLoader loader=new URLClassLoader(new URL[]{bad.toUri().toURL()},null)) {
            fails(IllegalArgumentException.class,()->new AssetManager(loader).list(""));
        }
    }
    public static void main(String[] args) throws Exception {
        Path root=Path.of(args[0]);filesystem(root);jars(root);
        System.out.println("PASS desktop database/package/resource/asset IO: "+checks+" checks");
    }
}
