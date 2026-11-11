/* Copyright 2026 uds-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only */
#ifdef NDEBUG
#error Assertions must remain enabled
#endif
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#include "zip.h"
#include "unzip.h"
static unsigned char payload[512];
static void write_zip(const char *path,const char *password) {
    zipFile zip=zipOpen(path,APPEND_STATUS_CREATE);assert(zip);
    unsigned long crc=crc32(0,payload,sizeof(payload));
    assert(zipOpenNewFileInZip3(zip,"binary.dat",NULL,NULL,0,NULL,0,NULL,0,0,0,
        -MAX_WBITS,8,Z_DEFAULT_STRATEGY,password,crc)==ZIP_OK);
    assert(zipWriteInFileInZip(zip,payload,sizeof(payload))==ZIP_OK);
    assert(zipCloseFileInZip(zip)==ZIP_OK);assert(zipClose(zip,NULL)==ZIP_OK);
}
static int read_zip(const char *path,const char *password) {
    unzFile zip=libkml_unzOpen(path);if(!zip)return 0;
    int open=libkml_unzOpenCurrentFilePassword(zip,password);
    if(open!=UNZ_OK){libkml_unzClose(zip);return 0;}
    unsigned char bytes[513];unsigned total=0;int n;
    while(total<sizeof(bytes)&&(n=libkml_unzReadCurrentFile(zip,bytes+total,sizeof(bytes)-total))>0)total+=n;
    int close=libkml_unzCloseCurrentFile(zip);assert(libkml_unzClose(zip)==UNZ_OK);
    return n==0&&close==UNZ_OK&&total==sizeof(payload)&&!memcmp(payload,bytes,total);
}
int main(int argc,char **argv) {
    assert(argc==2);for(unsigned i=0;i<sizeof(payload);i++)payload[i]=(unsigned char)i;
    char plain[4096],encrypted[4096];
    assert(snprintf(plain,sizeof(plain),"%s/plain.zip",argv[1])<(int)sizeof(plain));
    assert(snprintf(encrypted,sizeof(encrypted),"%s/encrypted.zip",argv[1])<(int)sizeof(encrypted));
    write_zip(plain,NULL);assert(read_zip(plain,NULL));
    FILE *f=fopen(plain,"r+b");assert(f);unsigned char header[30];assert(fread(header,1,30,f)==30);
    assert(!memcmp(header,"PK\003\004",4));long offset=30+header[26]+256*header[27]+header[28]+256*header[29];
    assert(fseek(f,offset,SEEK_SET)==0);int value=fgetc(f);assert(value!=EOF);
    assert(fseek(f,offset,SEEK_SET)==0&&fputc(value^1,f)!=EOF);assert(fclose(f)==0);
    assert(!read_zip(plain,NULL));
    write_zip(encrypted,"fixture-password");assert(read_zip(encrypted,"fixture-password"));
    assert(!read_zip(encrypted,"wrong-fixture-password"));
    puts("real_minizip_binary_crc_correct_and_wrong_password_controls=true");
}
