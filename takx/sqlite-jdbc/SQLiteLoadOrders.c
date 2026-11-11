/* Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only */
#define _GNU_SOURCE
#include <jni.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"failed line%d: %s\n",__LINE__,#x);return 1;}}while(0)
static int jdbc(JNIEnv *env,const char *native){
 jclass cls=(*env)->FindClass(env,"SQLiteSourceSmoke");if(!cls)return 0;
 jmethodID main=(*env)->GetStaticMethodID(env,cls,"main","([Ljava/lang/String;)V");if(!main)return 0;
 jclass string=(*env)->FindClass(env,"java/lang/String");if(!string)return 0;
 jobjectArray args=(*env)->NewObjectArray(env,1,string,NULL);if(!args)return 0;
 jstring path=(*env)->NewStringUTF(env,native);(*env)->SetObjectArrayElement(env,args,0,path);
 (*env)->CallStaticVoidMethod(env,cls,main,args);
 if((*env)->ExceptionCheck(env)){(*env)->ExceptionDescribe(env);return 0;}return 1;
}
int main(int argc,char **argv){
 CHECK(argc==8);int jfirst=!strcmp(argv[1],"jm");CHECK(jfirst||!strcmp(argv[1],"mj"));
 void *first=dlopen(argv[jfirst?2:3],RTLD_NOW|RTLD_GLOBAL);if(!first)fprintf(stderr,"%s\n",dlerror());CHECK(first);
 void *second=dlopen(argv[jfirst?3:2],RTLD_NOW|RTLD_GLOBAL);if(!second)fprintf(stderr,"%s\n",dlerror());CHECK(second);
 void *modern=jfirst?second:first;
 const char *(*version)(void)=dlsym(modern,"m_version");int (*aes)(void)=dlsym(modern,"m_aes"),(*database)(const char*)=dlsym(modern,"m_database");
 CHECK(version&&aes&&database);CHECK(!strncmp(version(),"OpenSSL 3.5.9",13));CHECK(dlsym(RTLD_DEFAULT,"sqlite3_libversion")==NULL);CHECK(dlsym(RTLD_DEFAULT,"sqlite3_key")==NULL);
 JavaVMOption options[6];char *properties[]={argv[4],argv[5],argv[6],"-XX:ActiveProcessorCount=2","-Xmx256m","-XX:-UsePerfData"};
 for(int i=0;i<6;i++)options[i].optionString=properties[i];
 JavaVMInitArgs init={0};init.version=JNI_VERSION_1_8;init.nOptions=6;init.options=options;init.ignoreUnrecognized=JNI_FALSE;
 JavaVM *vm;JNIEnv *env;CHECK(JNI_CreateJavaVM(&vm,(void**)&env,&init)==JNI_OK);
 CHECK(jdbc(env,argv[2]));CHECK(aes());CHECK(database(argv[7]));CHECK(jdbc(env,argv[2]));CHECK(aes());
 printf("order=%s\nmodern=%s\njdbc_plain_and_sqlcipher_encrypted_controls=PASS\n",argv[1],version());
 FILE *f=fopen("/proc/self/maps","r");CHECK(f);char line[4096];while(fgets(line,sizeof line,f))if(strchr(line,'/'))printf("map=%s",line);fclose(f);
 CHECK((*vm)->DestroyJavaVM(vm)==JNI_OK);CHECK(dlclose(second)==0);CHECK(dlclose(first)==0);return 0;
}
