// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
package com.atakmap.map.gdal;

import com.atakmap.coremap.filesystem.FileSystemUtils;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;

/** Calls the unchanged pinned public handler, its default IO provider and Os.stat. */
public final class VsiFileHandlerTest {
    private static int checks;
    private static void check(boolean value,String message) {
        checks++; if(!value) throw new AssertionError(message);
    }
    public static void main(String[] args) throws Exception {
        Path root=Path.of(args[0]);
        // Public User mount mode limits discovery/migration to this temporary root.
        FileSystemUtils.setMountPoint(root.toFile());
        VSIFileFileSystemHandler handler=new VSIFileFileSystemHandler();
        String prefix=VSIFileFileSystemHandler.PREFIX;
        Path payload=root.resolve("payload"); byte[] bytes=Files.readAllBytes(payload);
        VSIStatBuf result=new VSIStatBuf();
        check(handler.stat(prefix+payload,result,0)==0,"unchanged handler stat succeeds");
        check(result.st_size==bytes.length && result.st_blksize==512 && result.st_blocks==9,"upstream virtual size/block policy");
        long[] actual={result.st_dev,result.st_ino,result.st_rdev,Integer.toUnsignedLong(result.st_uid),Integer.toUnsignedLong(result.st_gid)};
        String[] expected=Files.readString(root.resolve("template-stat.txt")).strip().split(" ");
        for(int i=0;i<5;i++) check(actual[i]==Long.parseLong(expected[i]),"handler uses real template identity field " + i);
        check(result.st_mtime==Files.getLastModifiedTime(payload).toMillis(),"upstream virtual timestamps remain milliseconds");
        check(Files.exists(root.resolve("atak/.stat")),"real initialization template exists");
        try(FileChannel channel=handler.open(prefix+payload,"rb")) {
            ByteBuffer data=ByteBuffer.allocate(bytes.length); while(data.hasRemaining() && channel.read(data)!=-1) { }
            check(java.util.Arrays.equals(data.array(),bytes),"unchanged handler reads real payload");
        }
        Path written=root.resolve("written");
        try(FileChannel channel=handler.open(prefix+written,"wb+")) { channel.write(ByteBuffer.wrap(new byte[]{11,22,33})); }
        check(java.util.Arrays.equals(Files.readAllBytes(written),new byte[]{11,22,33}),"unchanged access-mode conversion writes real file");
        check(handler.stat(prefix+root.resolve("missing"),new VSIStatBuf(),0)==-1,"missing virtual file");
        check(handler.stat(payload.toString(),new VSIStatBuf(),0)==-1,"foreign prefix stat rejected");
        check(handler.open(payload.toString(),"r")==null,"foreign prefix open rejected");
        VSIStatBuf directory=new VSIStatBuf(); check(handler.stat(prefix+root,directory,0)==0
                && (directory.st_mode & 0040000)!=0,"unchanged directory mode policy");
        VSIStatBuf link=new VSIStatBuf(); check(handler.stat(prefix+root.resolve("payload-link"),link,0)==0
                && link.st_size==bytes.length,"virtual stat follows a real symlink");
        check(FileSystemUtils.getDeviceRoots().length==1
                && FileSystemUtils.getDeviceRoots()[0].equals(root.toFile()),"fixture uses only the explicit temporary mount");
        System.out.println("Unchanged Kernel VSI handler checks: " + checks);
    }
}
