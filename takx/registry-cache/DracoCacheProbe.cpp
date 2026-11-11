// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#include "draco/compression/decode.h"
#include "draco/compression/encode.h"
#include "draco/mesh/triangle_soup_mesh_builder.h"
#include <array>
#include <cassert>
#include <cmath>
#include <iostream>
#include <set>
int main() {
  const float positions[8][3] = {{0,0,0},{1,0,0},{1,1,0},{0,1,0},
                                {0,0,1},{1,0,1},{1,1,1},{0,1,1}};
  const int faces[12][3] = {{0,1,2},{0,2,3},{4,6,5},{4,7,6},{0,4,5},{0,5,1},
                            {1,5,6},{1,6,2},{2,6,7},{2,7,3},{3,7,4},{3,4,0}};
  const float normal[3] = {0,0,1}, uv[2] = {0,0};
  draco::TriangleSoupMeshBuilder builder;
  builder.Start(12);
  int p = builder.AddAttribute(draco::GeometryAttribute::POSITION,3,draco::DT_FLOAT32);
  int n = builder.AddAttribute(draco::GeometryAttribute::NORMAL,3,draco::DT_FLOAT32);
  int t = builder.AddAttribute(draco::GeometryAttribute::TEX_COORD,2,draco::DT_FLOAT32);
  assert(p >= 0 && n >= 0 && t >= 0);
  for (int i=0;i<12;++i) {
    builder.SetAttributeValuesForFace(p,draco::FaceIndex(i),positions[faces[i][0]],positions[faces[i][1]],positions[faces[i][2]]);
    builder.SetAttributeValuesForFace(n,draco::FaceIndex(i),normal,normal,normal);
    builder.SetAttributeValuesForFace(t,draco::FaceIndex(i),uv,uv,uv);
  }
  auto mesh = builder.Finalize();
  assert(mesh && mesh->num_faces() == 12 && mesh->num_attributes() == 3);
  draco::Encoder encoder;
  draco::EncoderBuffer encoded;
  assert(encoder.EncodeMeshToBuffer(*mesh,&encoded).ok() && encoded.size() > 1);
  draco::DecoderBuffer buffer;
  buffer.Init(encoded.data(),encoded.size());
  draco::Decoder decoder;
  auto result = decoder.DecodeMeshFromBuffer(&buffer);
  assert(result.ok());
  auto decoded = std::move(result).value();
  assert(decoded && decoded->num_faces() == 12 && decoded->num_attributes() == 3);
  auto *position = decoded->GetNamedAttribute(draco::GeometryAttribute::POSITION);
  assert(position && decoded->GetNamedAttribute(draco::GeometryAttribute::NORMAL) &&
         decoded->GetNamedAttribute(draco::GeometryAttribute::TEX_COORD));
  std::set<std::array<int,3>> corners;
  for (draco::PointIndex i(0);i<decoded->num_points();++i) {
    float xyz[3];
    assert((position->ConvertValue<float,3>(position->mapped_index(i),xyz)));
    std::array<int,3> corner;
    for (int d=0;d<3;++d) {
      corner[d] = std::lround(xyz[d]);
      assert(corner[d]>=0 && corner[d]<=1 && std::abs(xyz[d]-corner[d])<0.001f);
    }
    corners.insert(corner);
  }
  assert(corners.size()==8);
  draco::DecoderBuffer invalid;
  invalid.Init(encoded.data(),1);
  assert(!decoder.DecodeMeshFromBuffer(&invalid).ok());
  std::cout << "draco_cache_codec=pass;encode=true;faces=12;attributes=3;corners=8;truncation_rejected=true\n";
}
