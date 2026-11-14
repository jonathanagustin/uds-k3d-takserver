// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#include "renderer/feature/TextureFillMath.h"
#include <cassert>
#include <cmath>
using TAK::Engine::Renderer::Feature::TextureFillFrame;
static bool near(double a,double b){return std::abs(a-b)<1e-9;}
int main(){
 TextureFillFrame f;assert(f.initialize({{100,200}},{{100,201}},0,true));
 f.include({{100,200}});f.include({{164,264}});assert(f.valid());
 int repeat[]={0,0};float dim[]={32,32};std::array<double,2> uv;
 assert(f.sample(uv,{{140,244}},repeat,dim));assert(near(uv[0],0.25)&&near(uv[1],0.375));
 assert(f.sample(uv,{{92,188}},repeat,dim));assert(near(uv[0],0.75)&&near(uv[1],0.625));
 int mixed[]={1,0};assert(f.sample(uv,{{116,244}},mixed,dim));assert(near(uv[0],0.25)&&near(uv[1],0.375));
 TextureFillFrame rotated;assert(rotated.initialize({{0,0}},{{0,1}},90,true));
 rotated.include({{0,0}});rotated.include({{64,64}});assert(rotated.sample(uv,{{8,12}},repeat,dim));assert(near(uv[0],0.625)&&near(uv[1],0.25));
 TextureFillFrame north;assert(north.initialize({{0,0}},{{1,0}},0,true));north.include({{0,0}});north.include({{64,64}});
 assert(north.sample(uv,{{8,12}},repeat,dim));assert(near(uv[0],0.625)&&near(uv[1],0.25));
 TextureFillFrame screen;assert(screen.initialize({{0,0}},{{1,0}},0,false));screen.include({{0,0}});screen.include({{64,64}});
 assert(screen.sample(uv,{{8,12}},repeat,dim));assert(near(uv[0],0.25)&&near(uv[1],0.375));
 TextureFillFrame invalid;assert(!invalid.initialize({{0,0}},{{0,0}},0,true));assert(!invalid.valid());
 int bad[]={2,0};assert(!f.sample(uv,{{140,244}},bad,dim));
 float m[]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};int viewport[]={7,11,64,64};std::array<double,2> p;
 assert(TextureFillFrame::project(p,m,0,0,0,viewport));assert(near(p[0],39)&&near(p[1],43));
 return 0;
}
