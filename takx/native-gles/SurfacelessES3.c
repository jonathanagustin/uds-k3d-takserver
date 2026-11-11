/* Copyright 2026 uds-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <link.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"failed line %d: %s egl=0x%x gl=0x%x\n",__LINE__,#x,eglGetError(),glGetError()); exit(2); } } while (0)
static int provider(struct dl_phdr_info *i, size_t size, void *data) {
    (void)size; (void)data;
    if (i->dlpi_name && i->dlpi_name[0]) puts(i->dlpi_name);
    return 0;
}
int main(void) {
    EGLDisplay display=eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA,EGL_DEFAULT_DISPLAY,NULL);
    CHECK(display!=EGL_NO_DISPLAY);
    EGLint major=0,minor=0;CHECK(eglInitialize(display,&major,&minor));
    CHECK(eglBindAPI(EGL_OPENGL_ES_API));
    EGLint attributes[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT_KHR,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};
    EGLConfig config;EGLint count=0;CHECK(eglChooseConfig(display,attributes,&config,1,&count)&&count==1);
    EGLint surface_attrs[]={EGL_WIDTH,4,EGL_HEIGHT,4,EGL_NONE};
    EGLSurface surface=eglCreatePbufferSurface(display,config,surface_attrs);CHECK(surface!=EGL_NO_SURFACE);
    EGLint context_attrs[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};
    EGLContext context=eglCreateContext(display,config,EGL_NO_CONTEXT,context_attrs);CHECK(context!=EGL_NO_CONTEXT);
    CHECK(eglMakeCurrent(display,surface,surface,context));
    GLint glmajor=0;glGetIntegerv(GL_MAJOR_VERSION,&glmajor);CHECK(glmajor>=3);
    const char *renderer=(const char *)glGetString(GL_RENDERER);const char *version=(const char *)glGetString(GL_VERSION);
    CHECK(renderer && strstr(renderer,"llvmpipe") && version && strstr(version,"OpenGL ES 3."));
    glViewport(0,0,4,4);glClearColor(0.25f,0.5f,0.75f,1.0f);glClear(GL_COLOR_BUFFER_BIT);glFinish();CHECK(glGetError()==GL_NO_ERROR);
    unsigned char pixel[4]={0};glReadPixels(1,1,1,1,GL_RGBA,GL_UNSIGNED_BYTE,pixel);CHECK(glGetError()==GL_NO_ERROR);
    CHECK(abs((int)pixel[0]-64)<=1 && abs((int)pixel[1]-128)<=1 && abs((int)pixel[2]-191)<=1 && pixel[3]==255);
    printf("egl=%d.%d\nversion=%s\nrenderer=%s\npixel=%u,%u,%u,%u\nreal_surfaceless_es3_clear_readback=true\n",major,minor,version,renderer,pixel[0],pixel[1],pixel[2],pixel[3]);
    puts("providers_begin");dl_iterate_phdr(provider,NULL);puts("providers_end");
    CHECK(eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT));
    CHECK(eglDestroyContext(display,context));CHECK(eglDestroySurface(display,surface));CHECK(eglTerminate(display));
    return 0;
}
