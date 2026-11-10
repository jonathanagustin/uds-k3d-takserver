// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#include "draco/compression/decode.h"
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <iterator>
#include <set>
#include <array>
#include <vector>
int main(int argc, char **argv) {
 assert(argc==2);
 std::ifstream input(argv[1],std::ios::binary);
 std::vector<char> bytes((std::istreambuf_iterator<char>(input)),{});
 assert(bytes.size()==187);
 draco::DecoderBuffer buffer;buffer.Init(bytes.data(),bytes.size());
 auto type=draco::Decoder::GetEncodedGeometryType(&buffer);
 assert(type.ok() && type.value()==draco::TRIANGULAR_MESH);
 draco::Decoder decoder;auto decoded=decoder.DecodeMeshFromBuffer(&buffer);
 assert(decoded.ok());auto mesh=std::move(decoded).value();
 assert(mesh && mesh->num_faces()==12 && mesh->num_attributes()==3);
 auto *pos=mesh->GetNamedAttribute(draco::GeometryAttribute::POSITION);
 assert(pos && mesh->GetNamedAttribute(draco::GeometryAttribute::NORMAL) && mesh->GetNamedAttribute(draco::GeometryAttribute::TEX_COORD));
 std::set<std::array<int,3>> corners;
 for(draco::PointIndex i(0);i<mesh->num_points();++i) {
  float xyz[3];assert((pos->ConvertValue<float,3>(pos->mapped_index(i),xyz)));std::array<int,3> corner;
  for(int d=0;d<3;++d){corner[d]=std::lround(xyz[d]);assert(corner[d]>=0 && corner[d]<=1 && std::abs(xyz[d]-corner[d])<0.001f);}
  corners.insert(corner);
 }
 assert(corners.size()==8);
 draco::DecoderBuffer invalid;invalid.Init(bytes.data(),1);
 auto rejected=decoder.DecodeMeshFromBuffer(&invalid);assert(!rejected.ok());
 std::cout << "draco_source_codec_consumer=pass;faces=12;attributes=3;unique_corners=8;truncation_rejected=true\n";
}
