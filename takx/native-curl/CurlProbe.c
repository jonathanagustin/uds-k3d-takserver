/* Copyright 2026 uds-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only */
#define _GNU_SOURCE
#include <curl/curl.h>
#include <link.h>
#include <stdio.h>
#include <string.h>
static int encoded(const char *input,int length,const char *expected) {
  char *value=curl_escape(input,length);
  int ok=value && strcmp(value,expected)==0;
  curl_free(value);
  return ok;
}
static int providers(struct dl_phdr_info *info,size_t size,void *data) {
  (void)size;(void)data;
  if(info->dlpi_name && *info->dlpi_name && strcmp(info->dlpi_name,"linux-vdso.so.1"))
    printf("provider=%s\n",info->dlpi_name);
  return 0;
}
int main(void) {
  if(curl_global_init(CURL_GLOBAL_DEFAULT)!=CURLE_OK)return 1;
  const curl_version_info_data *v=curl_version_info(CURLVERSION_NOW);
  if(!v || strcmp(v->version,"8.23.0") || !v->ssl_version || strcmp(v->ssl_version,"OpenSSL/3.5.9") || !v->libz_version || strcmp(v->libz_version,"1.3.1"))return 2;
  if(!(v->features&CURL_VERSION_SSL) || !(v->features&CURL_VERSION_LIBZ))return 3;
  if(v->features&(CURL_VERSION_HTTP2|CURL_VERSION_HTTP3|CURL_VERSION_IDN|CURL_VERSION_PSL|CURL_VERSION_BROTLI|CURL_VERSION_ZSTD))return 4;
  int http=0,https=0;
  for(const char *const *p=v->protocols;*p;++p) {
    if(!strcmp(*p,"http"))http=1;
    if(!strcmp(*p,"https"))https=1;
    if(!strcmp(*p,"scp") || !strcmp(*p,"sftp") || !strcmp(*p,"ldap") || !strcmp(*p,"ldaps"))return 5;
  }
  if(!http || !https)return 6;
  const char binary[]={'a','\0','b'};
  for(int i=0;i<64;i++) {
    if(!encoded("a b/?&=+#%",0,"a%20b%2F%3F%26%3D%2B%23%25") || !encoded("\xc3\xa9 /?&",0,"%C3%A9%20%2F%3F%26") || !encoded(binary,3,"a%00b") || !encoded("",0,""))return 7;
  }
  CURL *easy=curl_easy_init();if(!easy)return 8;
  char *value=curl_easy_escape(easy,"real handle",0);
  int ok=value && !strcmp(value,"real%20handle");curl_free(value);curl_easy_cleanup(easy);
  curl_global_cleanup();if(!ok)return 9;
  puts("curl_8.23.0_escape_free_backend_feature_controls=true");
  dl_iterate_phdr(providers,NULL);
  return 0;
}
