// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
/* Local ordinary SQLCipher C API control; not a shipped application. */
#include "sqlite3.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/crypto.h>
static void require(int ok,const char *what){if(!ok){fprintf(stderr,"failed: %s\n",what);exit(1);}}
static void exec_ok(sqlite3 *db,const char *sql){char *error=0;int rc=sqlite3_exec(db,sql,0,0,&error);if(rc!=SQLITE_OK){fprintf(stderr,"SQL control failed rc=%d\n",rc);sqlite3_free(error);exit(1);}}
int main(int argc,char **argv){
 require(argc==2,"private fixture path"); sqlite3 *db=0; sqlite3_stmt *st=0;
 require(sqlite3_open(argv[1],&db)==SQLITE_OK,"create");
 require(sqlite3_key(db,"component-fixture-key",21)==SQLITE_OK,"sqlite3_key");
 require(sqlite3_prepare_v2(db,"PRAGMA cipher_version",-1,&st,0)==SQLITE_OK,"cipher version prepare");
 require(sqlite3_step(st)==SQLITE_ROW,"cipher version row");printf("cipher_version=%s\n",sqlite3_column_text(st,0));sqlite3_finalize(st);
 exec_ok(db,"CREATE TABLE control(id INTEGER PRIMARY KEY, label TEXT, value REAL); INSERT INTO control VALUES(7,'source-built SQLCipher',12.5);");
 require(sqlite3_close(db)==SQLITE_OK,"close");
 FILE *f=fopen(argv[1],"rb");unsigned char h[16];require(f&&fread(h,1,16,f)==16,"header");fclose(f);require(memcmp(h,"SQLite format 3",15)!=0,"encrypted header");
 require(sqlite3_open(argv[1],&db)==SQLITE_OK,"reopen"); require(sqlite3_key(db,"component-fixture-key",21)==SQLITE_OK,"reopen key");
 require(sqlite3_prepare_v2(db,"SELECT id,label,value FROM control",-1,&st,0)==SQLITE_OK,"query prepare");require(sqlite3_step(st)==SQLITE_ROW,"query row");
 require(sqlite3_column_int(st,0)==7&&!strcmp((const char*)sqlite3_column_text(st,1),"source-built SQLCipher")&&sqlite3_column_double(st,2)==12.5,"exact values");require(sqlite3_step(st)==SQLITE_DONE,"one row");sqlite3_finalize(st);require(sqlite3_close(db)==SQLITE_OK,"reclose");
 require(sqlite3_open(argv[1],&db)==SQLITE_OK,"wrong key open");require(sqlite3_key(db,"wrong-fixture-key",17)==SQLITE_OK,"wrong key setter");
 int rc=sqlite3_prepare_v2(db,"SELECT count(*) FROM sqlite_master",-1,&st,0);if(rc==SQLITE_OK)rc=sqlite3_step(st);require(rc==SQLITE_NOTADB,"wrong key rejected as not database");sqlite3_finalize(st);require(sqlite3_close(db)==SQLITE_OK,"wrong key close");
 printf("openssl=%s\nsqlite=%s\nencrypt_reopen_wrong_key=PASS\n",OpenSSL_version(OPENSSL_VERSION),sqlite3_libversion());return 0;
}
