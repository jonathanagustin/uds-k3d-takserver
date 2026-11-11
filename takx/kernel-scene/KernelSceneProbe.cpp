// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#ifdef NDEBUG
#error Assertions must remain enabled
#endif
#include "model/ASSIMPSceneSpi.h"
#include "model/Material.h"
#include "math/Matrix2.h"
#include <link.h>
#include <cassert>
#include <cmath>
#include <iostream>
#include <set>
#include <tuple>
using namespace TAK::Engine;
using namespace TAK::Engine::Model;
using namespace TAK::Engine::Util;
static bool near(double a, double b) { return std::abs(a-b)<1e-4; }
static void visit(SceneNode &node, unsigned &meshes, unsigned depth=0) {
    assert(depth<16);
    if(node.hasMesh()) {
        std::shared_ptr<const Mesh> mesh;
        assert(node.loadMesh(mesh)==TE_Ok && mesh);
        assert(mesh->getNumFaces()==1 && mesh->getNumVertices()==3);
        std::set<std::tuple<int,int,int>> positions;
        std::set<std::pair<int,int>> uv;
        for(unsigned i=0;i<3;i++) {
            Math::Point2<double> p;
            assert(mesh->getPosition(&p,i)==TE_Ok);
            assert(near(p.x,std::round(p.x)) && near(p.y,std::round(p.y)) && near(p.z,std::round(p.z)));
            positions.emplace(std::lround(p.x),std::lround(p.y),std::lround(p.z));
            Math::Point2<float> t;
            assert(mesh->getTextureCoordinate(&t,TEVA_TexCoord0,i)==TE_Ok);
            uv.emplace(std::lround(t.x*1000),std::lround(t.y*1000));
            Math::Point2<float> n;
            assert(mesh->getNormal(&n,i)==TE_Ok);
            assert(near(n.x,0) && near(n.y,0) && near(n.z,1));
            unsigned color=0;
            assert(mesh->getColor(&color,i)==TE_Ok && color==0xff3366ccu);
        }
        assert((positions==std::set<std::tuple<int,int,int>>{{12,26,42},{18,26,42},{12,38,42}}));
        // Kernel preserves its genuine Assimp adapter's UV convention.
        assert((uv==std::set<std::pair<int,int>>{{125,750},{750,750},{125,125}}));
        assert(mesh->getNumMaterials()==1);
        Material material;
        assert(mesh->getMaterial(&material,0)==TE_Ok);
        assert(material.propertyType==Material::TEPT_Diffuse);
        assert(material.color==0xffffffffu);
        meshes++;
    }
    if(node.hasChildren()) {
        Port::Collection<std::shared_ptr<SceneNode>>::IteratorPtr it(nullptr,nullptr);
        assert(node.getChildren(it)==TE_Ok && it);
        for(;;) {
            std::shared_ptr<SceneNode> child;
            auto code=it->get(child);
            if(code==TE_Done) break;
            assert(code==TE_Ok && child);
            visit(*child,meshes,depth+1);
            code=it->next();
            if(code==TE_Done) break;
            assert(code==TE_Ok);
        }
    }
}
static int provider(dl_phdr_info *info, size_t, void *) {
    if(info->dlpi_name && *info->dlpi_name) std::cout << "provider=" << info->dlpi_name << "\n";
    return 0;
}
int main(int argc,char **argv) {
    assert(argc==3);
    ASSIMPSceneSpi spi;
    for(int repeat=0;repeat<2;repeat++) {
        ScenePtr scene(nullptr,nullptr);
        assert(spi.create(scene,argv[1],nullptr,nullptr)==TE_Ok && scene);
        unsigned meshes=0;
        visit(scene->getRootNode(),meshes);
        assert(meshes==1);
        const auto &a=scene->getAABB();
        assert(near(a.minX,12)&&near(a.minY,26)&&near(a.minZ,42));
        assert(near(a.maxX,18)&&near(a.maxY,38)&&near(a.maxZ,42));
    }
    ScenePtr missing(nullptr,nullptr);
    assert(spi.create(missing,argv[2],nullptr,nullptr)!=TE_Ok && !missing);
    dl_iterate_phdr(provider,nullptr);
    std::cout << "actual_kernel_assimp_scene_geometry_material_uv_bounds_bad_uri=true\n";
}
