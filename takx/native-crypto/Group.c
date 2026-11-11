/* Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only */
/* Owned experiment entrypoints, never SDK replacements. */
#include <openssl/crypto.h>
#include <openssl/opensslv.h>
#include <openssl/evp.h>
#include <string.h>
#ifdef QUICTLS_GROUP
#include <openssl/ssl.h>
#define API(n) q_##n
static size_t handshake_bytes;
static int secrets(SSL *s, OSSL_ENCRYPTION_LEVEL l, const uint8_t *r, const uint8_t *w, size_t n) {(void)s;(void)l;(void)r;(void)w;(void)n;return 1;}
static int handshake(SSL *s, OSSL_ENCRYPTION_LEVEL l, const uint8_t *p,size_t n) {(void)s;if(l!=ssl_encryption_initial||!p||!n)return 0;handshake_bytes+=n;return 1;}
static int flush(SSL *s) {(void)s;return 1;}
static int alert(SSL *s,enum ssl_encryption_level_t l,uint8_t a) {(void)s;(void)l;(void)a;return 1;}
int q_quic(void) {
 SSL_QUIC_METHOD methods={secrets,handshake,flush,alert};
 SSL_CTX *ctx=SSL_CTX_new(TLS_client_method());if(!ctx)return 0;
 if(!SSL_CTX_set_min_proto_version(ctx,TLS1_3_VERSION)||!SSL_CTX_set_max_proto_version(ctx,TLS1_3_VERSION)||!SSL_CTX_set_quic_method(ctx,&methods)){SSL_CTX_free(ctx);return 0;}
 SSL *ssl=SSL_new(ctx);if(!ssl){SSL_CTX_free(ctx);return 0;}
 const unsigned char params[]={0x01,0x01,0x00};
 int ok=SSL_set_quic_transport_params(ssl,params,sizeof params)&&SSL_is_quic(ssl);
 SSL_set_connect_state(ssl);handshake_bytes=0;
 int rc=SSL_do_handshake(ssl);ok=ok&&rc!=1&&SSL_get_error(ssl,rc)==SSL_ERROR_WANT_READ&&handshake_bytes>0;
 SSL_free(ssl);SSL_CTX_free(ctx);return ok;
}
#else
#define API(n) m_##n
#define main private_sqlcipher_control_main
#include "SqlcipherSourceProbe.c"
#undef main
int m_database(const char *path) {char *argv[]={(char*)"owned-crypto-experiment",(char*)path,0};return private_sqlcipher_control_main(2,argv)==0;}
#endif
const char *API(version)(void) {return OpenSSL_version_num()==OPENSSL_VERSION_NUMBER?OpenSSL_version(OPENSSL_VERSION):"header-runtime-mismatch";}
int API(aes)(void) {
 const unsigned char key[]={0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15};
 const unsigned char plain[]={0,0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88,0x99,0xaa,0xbb,0xcc,0xdd,0xee,0xff};
 const unsigned char known[]={0x69,0xc4,0xe0,0xd8,0x6a,0x7b,0x04,0x30,0xd8,0xcd,0xb7,0x80,0x70,0xb4,0xc5,0x5a};
 unsigned char out[32],back[32];int n=0,z=0;EVP_CIPHER_CTX *ctx=EVP_CIPHER_CTX_new();if(!ctx)return 0;
 int ok=EVP_EncryptInit_ex(ctx,EVP_aes_128_ecb(),0,key,0)&&EVP_CIPHER_CTX_set_padding(ctx,0)&&EVP_EncryptUpdate(ctx,out,&n,plain,16)&&EVP_EncryptFinal_ex(ctx,out+n,&z)&&n+z==16&&!memcmp(out,known,16);
 ok=ok&&EVP_DecryptInit_ex(ctx,EVP_aes_128_ecb(),0,key,0)&&EVP_CIPHER_CTX_set_padding(ctx,0)&&EVP_DecryptUpdate(ctx,back,&n,out,16)&&EVP_DecryptFinal_ex(ctx,back+n,&z)&&n+z==16&&!memcmp(back,plain,16);
 EVP_CIPHER_CTX_free(ctx);return ok;
}
