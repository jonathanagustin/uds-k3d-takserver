/* Copyright 2026 uds-takserver authors */
/* SPDX-License-Identifier: GPL-3.0-only */
#ifdef NDEBUG
#error Probe assertions must remain enabled
#endif
#include <assimp/cimport.h>
#include <assimp/scene.h>
#include <assimp/postprocess.h>
#include <assimp/material.h>
#include <assimp/version.h>
#include <assert.h>
#include <math.h>
#include <stdio.h>
static int near(double a,double b){return fabs(a-b)<1e-4;}
static void node_check(const struct aiScene* scene,const struct aiNode* node,const struct aiMatrix4x4* parent,unsigned* count){
    struct aiMatrix4x4 world=*parent;aiMultiplyMatrix4(&world,&node->mTransformation);
    for(unsigned i=0;i<node->mNumMeshes;++i){
        assert(node->mMeshes[i]<scene->mNumMeshes);const struct aiMesh* mesh=scene->mMeshes[node->mMeshes[i]];
        for(unsigned j=0;j<mesh->mNumVertices;++j){struct aiVector3D p=mesh->mVertices[j];aiTransformVecByMatrix4(&p,&world);assert(near(p.x,10+2*mesh->mVertices[j].x)&&near(p.y,20+3*mesh->mVertices[j].y)&&near(p.z,30+4*mesh->mVertices[j].z));}
        ++*count;
    }
    for(unsigned i=0;i<node->mNumChildren;++i)node_check(scene,node->mChildren[i],&world,count);
}
int main(int argc,char**argv){
    assert(argc==2);const struct aiScene* scene=aiImportFile(argv[1],aiProcess_Triangulate|aiProcess_ValidateDataStructure);assert(scene&&scene->mNumMeshes==1&&scene->mRootNode);
    const struct aiMesh* mesh=scene->mMeshes[0];assert(mesh->mNumVertices==3&&mesh->mNumFaces==1&&mesh->mNormals&&mesh->mTextureCoords[0]);
    for(unsigned i=0;i<3;++i){assert(mesh->mFaces[0].mIndices[i]<3);assert(near(mesh->mNormals[i].z,1));}
    assert(mesh->mMaterialIndex<scene->mNumMaterials);struct aiColor4D color;assert(aiGetMaterialColor(scene->mMaterials[mesh->mMaterialIndex],AI_MATKEY_COLOR_DIFFUSE,&color)==aiReturn_SUCCESS);assert(near(color.r,0.2)&&near(color.g,0.4)&&near(color.b,0.8));
    struct aiMatrix4x4 identity;aiIdentityMatrix4(&identity);unsigned count=0;node_check(scene,scene->mRootNode,&identity,&count);assert(count==1);
    assert(aiGetVersionMajor()==4&&aiGetVersionMinor()==1);aiReleaseImport(scene);puts("pure_c_model_material_transform_probe=true");return 0;
}
