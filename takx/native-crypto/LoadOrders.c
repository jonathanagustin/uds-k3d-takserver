/* Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define REQUIRE(x) do{if(!(x)){fprintf(stderr,"failure line %d: %s: %s\n",__LINE__,#x,dlerror());return 1;}}while(0)
int main(int argc,char **argv){
 REQUIRE(argc==5);int firstq=!strcmp(argv[1],"qm");
 void *first=dlopen(argv[firstq?2:3],RTLD_NOW|RTLD_GLOBAL);REQUIRE(first);
 void *second=dlopen(argv[firstq?3:2],RTLD_NOW|RTLD_GLOBAL);REQUIRE(second);
 void *q=firstq?first:second,*m=firstq?second:first;
 const char *(*qv)(void)=dlsym(q,"q_version"),*(*mv)(void)=dlsym(m,"m_version");
 int (*qa)(void)=dlsym(q,"q_aes"),(*ma)(void)=dlsym(m,"m_aes"),(*quic)(void)=dlsym(q,"q_quic"),(*db)(const char*)=dlsym(m,"m_database");
 REQUIRE(qv&&mv&&qa&&ma&&quic&&db);
 REQUIRE(!strncmp(qv(),"OpenSSL 3.0.14",14));REQUIRE(!strncmp(mv(),"OpenSSL 3.5.9",13));
 REQUIRE(dlsym(RTLD_DEFAULT,"OpenSSL_version")==NULL);REQUIRE(dlsym(RTLD_DEFAULT,"EVP_EncryptInit_ex")==NULL);
 for(int i=0;i<3;i++){REQUIRE(qa());REQUIRE(ma());REQUIRE(quic());}
 REQUIRE(db(argv[4]));
 printf("order=%s\nquictls=%s\nmodern=%s\naes_both=PASS\nquictls_clienthello_callback=PASS\n",argv[1],qv(),mv());
 FILE *f=fopen("/proc/self/maps","r");REQUIRE(f);char line[4096];while(fgets(line,sizeof line,f))if(strchr(line,'/'))printf("map=%s",line);fclose(f);
 REQUIRE(dlclose(second)==0);REQUIRE(dlclose(first)==0);return 0;
}
