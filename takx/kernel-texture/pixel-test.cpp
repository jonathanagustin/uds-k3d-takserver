// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "renderer/Tessellate.h"
#include "renderer/feature/TextureFillMath.h"
using namespace TAK::Engine::Renderer;
using TAK::Engine::Renderer::Feature::TextureFillFrame;
using TAK::Engine::Math::Point2;
static const char *vertexSource =
#include "renderer/feature/BatchGeometryPolygons.vert"
;
static const char *fragmentSource =
#include "renderer/feature/BatchGeometryPolygons.frag"
;
#define CHECK(x) do { if(!(x)){std::fprintf(stderr,"failed line %d %s EGL=%x GL=%x\n",__LINE__,#x,eglGetError(),glGetError());std::exit(2);} } while(0)
struct Triangles: TessellateCallback {
 std::vector<float> xyz;
 TAK::Engine::Util::TAKErr point(const Point2<double>&p) NOTHROWS override {xyz.insert(xyz.end(),{float(p.x),float(p.y),float(p.z)});return TAK::Engine::Util::TE_Ok;}
};
static GLuint shader(GLenum type,const char*s){GLuint x=glCreateShader(type);glShaderSource(x,1,&s,nullptr);glCompileShader(x);GLint ok;glGetShaderiv(x,GL_COMPILE_STATUS,&ok);if(!ok){char log[4096];glGetShaderInfoLog(x,sizeof(log),nullptr,log);std::fprintf(stderr,"%s\n",log);}CHECK(ok);return x;}
static GLint uniform(GLuint p,const char*n){GLint v=glGetUniformLocation(p,n);CHECK(v>=0);return v;}
int main(){
 double outer[]={8,8,0,56,8,0,56,56,0,8,56,0,8,8,0};
 double hole[]={24,24,0,24,40,0,40,40,0,40,24,0,24,24,0};
 VertexData rings[2];rings[0].data=outer;rings[1].data=hole;for(auto&r:rings){r.size=3;r.stride=24;}
 int sizes[]={5,5};Triangles triangles;
 CHECK(Tessellate_polygon<double>(triangles,rings,sizes,2,0.0,Tessellate_CartesianAlgorithm())==TAK::Engine::Util::TE_Ok);
 CHECK(triangles.xyz.size()>=24 && triangles.xyz.size()%9==0);
 for(int cycle=0;cycle<3;cycle++){
  EGLDisplay display=eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA,EGL_DEFAULT_DISPLAY,nullptr);CHECK(display!=EGL_NO_DISPLAY);EGLint major,minor;CHECK(eglInitialize(display,&major,&minor));CHECK(eglBindAPI(EGL_OPENGL_ES_API));
  EGLint attrs[]={EGL_SURFACE_TYPE,EGL_PBUFFER_BIT,EGL_RENDERABLE_TYPE,EGL_OPENGL_ES3_BIT_KHR,EGL_RED_SIZE,8,EGL_GREEN_SIZE,8,EGL_BLUE_SIZE,8,EGL_ALPHA_SIZE,8,EGL_NONE};EGLConfig config;EGLint count;CHECK(eglChooseConfig(display,attrs,&config,1,&count)&&count==1);
  EGLint dimensions[]={EGL_WIDTH,64,EGL_HEIGHT,64,EGL_NONE};EGLSurface surface=eglCreatePbufferSurface(display,config,dimensions);CHECK(surface!=EGL_NO_SURFACE);EGLint ca[]={EGL_CONTEXT_CLIENT_VERSION,3,EGL_NONE};EGLContext context=eglCreateContext(display,config,EGL_NO_CONTEXT,ca);CHECK(context!=EGL_NO_CONTEXT);CHECK(eglMakeCurrent(display,surface,surface,context));
  GLuint v=shader(GL_VERTEX_SHADER,vertexSource),f=shader(GL_FRAGMENT_SHADER,fragmentSource),program=glCreateProgram();glAttachShader(program,v);glAttachShader(program,f);glLinkProgram(program);GLint ok;glGetProgramiv(program,GL_LINK_STATUS,&ok);CHECK(ok);glDeleteShader(v);glDeleteShader(f);glUseProgram(program);
  float m[]={2.f/64,0,0,0,0,2.f/64,0,0,0,0,1,0,-1,-1,0,1};glUniformMatrix4fv(uniform(program,"u_mvp"),1,GL_FALSE,m);glUniform4f(uniform(program,"u_color"),1,1,1,1);glUniform3f(glGetUniformLocation(program,"uLightingNormal"),0,0,1);
  GLuint buffer;glGenBuffers(1,&buffer);glBindBuffer(GL_ARRAY_BUFFER,buffer);glBufferData(GL_ARRAY_BUFFER,triangles.xyz.size()*sizeof(float),triangles.xyz.data(),GL_STATIC_DRAW);GLint position=glGetAttribLocation(program,"aPosition");CHECK(position>=0);glVertexAttribPointer(position,3,GL_FLOAT,GL_FALSE,0,nullptr);glEnableVertexAttribArray(position);
  glVertexAttrib4f(glGetAttribLocation(program,"a_color"),1,1,1,1);glVertexAttrib1f(glGetAttribLocation(program,"aExteriorVertex"),1);glVertexAttrib1f(glGetAttribLocation(program,"aOutlineWidth"),0);
  GLuint texture;glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);unsigned char image[8*4*4];for(int y=0;y<4;y++)for(int x=0;x<8;x++){int i=(y*8+x)*4;image[i]=x<4?((x+y)%2?255:40):255;image[i+1]=x<4?(x==y?200:20):0;image[i+2]=x<4?0:255;image[i+3]=x<4?((x==0&&y==0)?0:255):255;}
  glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,8,4,0,GL_RGBA,GL_UNSIGNED_BYTE,image);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
  glUniform1i(uniform(program,"uTextureEnabled"),1);glUniform1i(uniform(program,"uTexture"),0);glUniform4f(uniform(program,"uTextureAtlas"),0,0,.5,1);glUniform2f(uniform(program,"uTextureDimensions"),32,32);glViewport(0,0,64,64);
  int total=0;
  for(int mode=0;mode<4;mode++){
   TextureFillFrame frame;CHECK(frame.initialize({{32,32}},{{32,33}},mode==1?90:0,true));for(size_t i=0;i<triangles.xyz.size();i+=3)frame.include({{triangles.xyz[i],triangles.xyz[i+1]}});CHECK(frame.valid());int repeat[]={mode==2?1:0,mode==3?1:0};float dims[]={32,32};
   glUniform2f(uniform(program,"uTextureOrigin"),32,32);glUniform2f(uniform(program,"uTextureRotation"),frame.cosine,frame.sine);glUniform4f(uniform(program,"uTextureBounds"),frame.bounds[0],frame.bounds[1],frame.bounds[2],frame.bounds[3]);glUniform2i(uniform(program,"uTextureRepeat"),repeat[0],repeat[1]);
   glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT);glDrawArrays(GL_TRIANGLES,0,triangles.xyz.size()/3);glFinish();CHECK(glGetError()==GL_NO_ERROR);unsigned char pixels[64*64*4];glReadPixels(0,0,64,64,GL_RGBA,GL_UNSIGNED_BYTE,pixels);CHECK(glGetError()==GL_NO_ERROR);
   for(int y=0;y<64;y++)for(int x=0;x<64;x++){
    const unsigned char *got=pixels+(y*64+x)*4;bool inside=x>=8&&x<56&&y>=8&&y<56&&!(x>=24&&x<40&&y>=24&&y<40);
    if(!inside){CHECK(got[0]==0&&got[1]==0&&got[2]==0&&got[3]==0);continue;}
    std::array<double,2> uv;CHECK(frame.sample(uv,{{x+.5,y+.5}},repeat,dims));int tx=int(std::floor(.5+3*uv[0])),ty=int(std::floor(.5+3*uv[1]));const unsigned char *expected=image+(ty*8+tx)*4;
    CHECK(got[0]==expected[0]&&got[1]==expected[1]&&got[2]==expected[2]&&got[3]==expected[3]);total++;
   }
  }
  CHECK(total==8192);glDisableVertexAttribArray(position);glDeleteTextures(1,&texture);glDeleteBuffers(1,&buffer);glDeleteProgram(program);CHECK(glGetError()==GL_NO_ERROR);CHECK(eglMakeCurrent(display,EGL_NO_SURFACE,EGL_NO_SURFACE,EGL_NO_CONTEXT));CHECK(eglDestroyContext(display,context));CHECK(eglDestroySurface(display,surface));CHECK(eglTerminate(display));
  std::printf("PASS cycle=%d real_hole_tessellation=true pixel_checks=%d repeat_rotation_mixed_axes=true atlas_no_bleed=true\n",cycle,total);
 }
}
