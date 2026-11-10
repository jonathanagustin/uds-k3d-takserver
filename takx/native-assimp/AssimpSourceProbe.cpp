// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#ifdef NDEBUG
#error Probe assertions must remain enabled
#endif
#include <assimp/Importer.hpp>
#include <assimp/scene.h>
#include <assimp/postprocess.h>
#include <assimp/cimport.h>
#include <assimp/cexport.h>
#include <assimp/material.h>
#include <assimp/version.h>
#include <cassert>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <dlfcn.h>
#include <limits.h>
#include <cstdlib>

static bool near(double a,double b){return std::abs(a-b)<1e-4;}
static const unsigned flags=aiProcess_Triangulate|aiProcess_ValidateDataStructure|aiProcess_JoinIdenticalVertices;
static const char dae[]=R"XML(<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><created>2026-01-01T00:00:00Z</created><modified>2026-01-01T00:00:00Z</modified><unit name="meter" meter="1"/><up_axis>Y_UP</up_axis></asset>
<library_effects><effect id="fx"><profile_COMMON><technique sid="common"><lambert><diffuse><color>0.2 0.4 0.8 1</color></diffuse></lambert></technique></profile_COMMON></effect></library_effects>
<library_materials><material id="mat" name="Blue"><instance_effect url="#fx"/></material></library_materials>
<library_geometries><geometry id="triangle" name="Triangle"><mesh>
<source id="positions"><float_array id="position-array" count="9">1 2 3 4 2 3 1 6 3</float_array><technique_common><accessor source="#position-array" count="3" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="normals"><float_array id="normal-array" count="9">0 0 1 0 0 1 0 0 1</float_array><technique_common><accessor source="#normal-array" count="3" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="uv"><float_array id="uv-array" count="6">0.125 0.25 0.75 0.25 0.125 0.875</float_array><technique_common><accessor source="#uv-array" count="3" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles material="M" count="1"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="NORMAL" source="#normals" offset="1"/><input semantic="TEXCOORD" source="#uv" offset="2" set="0"/><p>0 0 0 1 1 1 2 2 2</p></triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="Scene"><node id="parent" name="parent"><translate>10 20 30</translate><node id="meshNode" name="meshNode"><scale>2 3 4</scale><instance_geometry url="#triangle"><bind_material><technique_common><instance_material symbol="M" target="#mat"/></technique_common></bind_material></instance_geometry></node></node></visual_scene></library_visual_scenes><scene><instance_visual_scene url="#Scene"/></scene></COLLADA>)XML";

static void check_node(const aiScene* scene,const aiNode* node,const aiMatrix4x4 &parent,unsigned &references){
    aiMatrix4x4 world=parent*node->mTransformation;
    for(unsigned i=0;i<node->mNumMeshes;++i){
        assert(node->mMeshes[i]<scene->mNumMeshes);const aiMesh* mesh=scene->mMeshes[node->mMeshes[i]];
        for(unsigned j=0;j<mesh->mNumVertices;++j){
            const aiVector3D local=mesh->mVertices[j];const aiVector3D point=world*local;
            assert(near(point.x,10+2*local.x)&&near(point.y,20+3*local.y)&&near(point.z,30+4*local.z));
        }
        ++references;
    }
    for(unsigned i=0;i<node->mNumChildren;++i)check_node(scene,node->mChildren[i],world,references);
}
static void check(const aiScene* scene){
    assert(scene && scene->mRootNode && scene->mNumMeshes==1);
    const aiMesh* mesh=scene->mMeshes[0];assert(mesh && mesh->mNumVertices==3 && mesh->mNumFaces==1);
    assert(mesh->mFaces[0].mNumIndices==3 && mesh->HasNormals() && mesh->HasTextureCoords(0));
    bool seen[3]={false,false,false};
    for(unsigned j=0;j<3;++j){
        unsigned i=mesh->mFaces[0].mIndices[j];assert(i<3);const aiVector3D &p=mesh->mVertices[i];
        unsigned expected=near(p.x,4)?1:(near(p.y,6)?2:0);assert(!seen[expected]);seen[expected]=true;
        assert(near(p.x,expected==1?4:1)&&near(p.y,expected==2?6:2)&&near(p.z,3));
        const aiVector3D &n=mesh->mNormals[i],&uv=mesh->mTextureCoords[0][i];
        assert(near(n.x,0)&&near(n.y,0)&&near(n.z,1));
        assert(near(uv.x,expected==1?0.75:0.125)&&near(uv.y,expected==2?0.875:0.25));
    }
    assert(mesh->mMaterialIndex<scene->mNumMaterials);aiColor4D color;
    assert(aiGetMaterialColor(scene->mMaterials[mesh->mMaterialIndex],AI_MATKEY_COLOR_DIFFUSE,&color)==AI_SUCCESS);
    assert(near(color.r,0.2)&&near(color.g,0.4)&&near(color.b,0.8)&&near(color.a,1));
    unsigned references=0;check_node(scene,scene->mRootNode,aiMatrix4x4(),references);assert(references==1);
}
int main(int argc,char**argv){
    assert(argc==2);std::cout.setf(std::ios::unitbuf);Dl_info info;assert(dladdr(reinterpret_cast<void*>(&aiGetVersionMajor),&info));char canonical[PATH_MAX];assert(realpath(info.dli_fname,canonical));std::cout<<"loaded_libassimp="<<canonical<<'\n';
    std::cout<<"api_version="<<aiGetVersionMajor()<<'.'<<aiGetVersionMinor()<<'.'<<aiGetVersionRevision()<<'\n';assert(aiGetVersionMajor()==4&&aiGetVersionMinor()==1);
    assert(sizeof(ai_real)==sizeof(float));assert(aiGetExportFormatCount()>0);
    std::cerr<<"phase=cpp-collada\n";Assimp::Importer importer;const aiScene* scene=importer.ReadFileFromMemory(dae,sizeof(dae)-1,flags,"dae");if(!scene)std::cerr<<importer.GetErrorString()<<'\n';check(scene);
    std::cerr<<"phase=c-collada\n";const aiScene* cscene=aiImportFileFromMemory(dae,sizeof(dae)-1,flags,"dae");check(cscene);aiReleaseImport(cscene);
    std::cerr<<"phase=export-roundtrip\n";const aiExportDataBlob* blob=aiExportSceneToBlob(scene,"assbin",0);assert(blob&&blob->data&&blob->size>128);std::vector<char> binary(static_cast<const char*>(blob->data),static_cast<const char*>(blob->data)+blob->size);aiReleaseExportBlob(blob);
    Assimp::Importer reader;check(reader.ReadFileFromMemory(binary.data(),binary.size(),flags,"assbin"));
    cscene=aiImportFileFromMemory(binary.data(),binary.size(),flags,"assbin");check(cscene);aiReleaseImport(cscene);
    std::ofstream output(std::string(argv[1])+"/roundtrip.assbin",std::ios::binary);output.write(binary.data(),binary.size());output.close();
    std::cout<<"valid_cpp_c_geometry_material_transform_uv_normal_export_roundtrip=true\n";
}
