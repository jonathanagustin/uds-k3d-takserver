// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
// Opt-in actual builder callback control. This does not substitute a bitmap loader or claim cache runtime proof.
#include "renderer/feature/GLGeometryBatchBuilder.h"
#include "feature/Polygon.h"
#include "feature/LineString.h"
#include "feature/Style.h"
#include "raster/osm/OSMUtils.h"
#include <cassert>
#include <cstring>
#include <cstdio>
#include <map>
#include <memory>
#include <vector>
using namespace TAK::Engine;
using namespace TAK::Engine::Renderer::Feature;
using namespace TAK::Engine::Util;
using namespace atakmap::feature;
struct Callback final : GLGeometryBatchBuilder::Callback3 {
    TAKErr textureResult{TE_Busy};
    unsigned iconCalls{0}, textureCalls{0};
    std::map<GLuint,std::vector<uint8_t>> buffers;
    TAKErr mapBuffer(GLuint *id,void **buffer,std::size_t n) NOTHROWS override {
        *id=static_cast<GLuint>(buffers.size()+1);auto &b=buffers[*id];b.resize(n,0xcd);*buffer=b.data();return TE_Ok;
    }
    TAKErr unmapBuffer(GLuint) NOTHROWS override {return TE_Ok;}
    TAKErr getElevation(double *v,double,double) NOTHROWS override {*v=0;return TE_Ok;}
    TAKErr getIcon(GLuint *id,float*,float*,float*,float*,std::size_t*,std::size_t*,float*,bool*,const char*) NOTHROWS override {++iconCalls;*id=999;return TE_Ok;}
    TAKErr getTexture(GLuint *id,float *u0,float *v0,float *u1,float *v1,std::size_t *w,std::size_t *h,const char *uri) NOTHROWS override {
        ++textureCalls;assert(std::strcmp(uri,"fixture://actual-texture")==0);
        if(textureResult!=TE_Ok)return textureResult;
        *id=123;*u0=0;*v0=0;*u1=1;*v1=1;*w=32;*h=32;return TE_Ok;
    }
    TAKErr addLabel(const Renderer::Core::GLLabel&) NOTHROWS override {return TE_Ok;}
    TAKErr addLabel(Renderer::Core::GLLabel&&) NOTHROWS override {return TE_Ok;}
    uint32_t reserveHitId() NOTHROWS override {return 0xff000001;}
    TAKErr getMesh(std::shared_ptr<const Model::Mesh>&,const char*) NOTHROWS override {return TE_Unsupported;}
};
static Polygon polygon(){
    LineString exterior(Geometry::_3D);exterior.addPoint(8,8,0);exterior.addPoint(56,8,0);exterior.addPoint(56,56,0);exterior.addPoint(8,56,0);exterior.addPoint(8,8,0);
    LineString hole(Geometry::_3D);hole.addPoint(24,24,0);hole.addPoint(24,40,0);hole.addPoint(40,40,0);hole.addPoint(40,24,0);hole.addPoint(24,24,0);
    Polygon result(exterior);result.addRing(hole);return result;
}
static TAKErr push(GLGeometryBatchBuilder &builder,const Polygon &geometry,const Style &style){
    TAK::Engine::Feature::Feature2 feature(1,1,"fixture",geometry,TAK::Engine::Feature::TEAM_ClampToGround,0.0,&style,static_cast<const atakmap::util::AttributeSet*>(nullptr),1);
    return builder.push(feature,static_cast<GLGeometryBatchBuilder::PushHints>(GLGeometryBatchBuilder::TessellationDisabled|GLGeometryBatchBuilder::SimplificationDisabled|GLGeometryBatchBuilder::AntiMeridianHandlingDisabled));
}
static void reset(GLGeometryBatchBuilder &builder,Callback &callback){
    GLGeometryBatchBuilder::BatchContext context;context.surfaceSrid=4326;context.spritesSrid=4326;context.relativeToCenter=Core::GeoPoint2(0,0,0,Core::HAE);context.resolution.tessellate=0;context.resolution.scene=atakmap::raster::osm::OSMUtils::mapnikTileResolution(10);
    assert(builder.reset(context,callback)==TE_Ok);
}
static CompositeStyle styled(bool textureFirst){
    std::vector<Style*> parts;
    Style *texture=new TextureFillStyle("fixture://actual-texture",0x80ffffff,0,0,32,32,0,true);
    Style *stroke=new BasicStrokeStyle(0xffff0000,2);
    if(textureFirst)parts={texture,stroke};else parts={stroke,texture};
    return CompositeStyle(parts);
}
int main(){
    const Polygon shape=polygon();BasicFillStyle solid(0xff112233);
    for(bool textureFirst:{false,true}){
        Callback callback;GLGeometryBatchBuilder builder;reset(builder,callback);auto composite=styled(textureFirst);
        assert(push(builder,shape,composite)==TE_Ok);assert(builder.getLastTextureState()==GLGeometryBatchBuilder::TextureState::Pending);
        assert(callback.buffers.empty());assert(callback.iconCalls==0); // no partial stroke/fill, no reference-point fallback
        assert(push(builder,shape,solid)==TE_Ok);assert(builder.getLastTextureState()==GLGeometryBatchBuilder::TextureState::None);assert(!callback.buffers.empty());assert(builder.flush()==TE_Ok);
    }
    {
        Callback callback;callback.textureResult=TE_Err;GLGeometryBatchBuilder builder;reset(builder,callback);auto composite=styled(false);
        assert(push(builder,shape,composite)==TE_Ok);assert(builder.getLastTextureState()==GLGeometryBatchBuilder::TextureState::Failed);assert(callback.buffers.empty());
        assert(push(builder,shape,solid)==TE_Ok);assert(!callback.buffers.empty());assert(callback.iconCalls==0);assert(builder.flush()==TE_Ok);
    }
    // Simulated load completion here controls only the callback result; the real builder must retry the entire feature.
    for(bool textureFirst:{false,true}){
        Callback callback;GLGeometryBatchBuilder builder;reset(builder,callback);auto composite=styled(textureFirst);
        assert(push(builder,shape,composite)==TE_Ok);assert(callback.buffers.empty());callback.textureResult=TE_Ok;
        assert(push(builder,shape,composite)==TE_Ok);assert(builder.getLastTextureState()==GLGeometryBatchBuilder::TextureState::Ready);assert(callback.buffers.size()==2);assert(callback.iconCalls==0);assert(builder.flush()==TE_Ok);
    }
    // Actual packed level-of-detail bytes must survive both texture/ordinary child orders; later ordinary features use defaults again.
    for(bool textureFirst:{false,true}){
        Callback callback;callback.textureResult=TE_Ok;GLGeometryBatchBuilder builder;reset(builder,callback);auto composite=styled(textureFirst);LevelOfDetailStyle levelStyle(composite,7,12);
        assert(push(builder,shape,levelStyle)==TE_Ok);assert(callback.buffers.size()==2);assert(builder.flush()==TE_Ok);
        const auto &polygonBytes=callback.buffers.at(textureFirst?1:2);const auto &strokeBytes=callback.buffers.at(textureFirst?2:1);
        assert(polygonBytes[22]==7&&polygonBytes[23]==12);assert(strokeBytes[38]==7&&strokeBytes[39]==12);
        assert(push(builder,shape,solid)==TE_Ok);assert(builder.getLastTextureState()==GLGeometryBatchBuilder::TextureState::None);assert(builder.flush()==TE_Ok);
    }
    std::puts("PASS_ACTUAL_BUILDER_PENDING_FAILED_SIBLING_RETRY_BOTH_STYLE_ORDERS_LOD");
}
