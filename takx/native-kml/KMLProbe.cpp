// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#include <kml/dom.h>
#include <kml/engine.h>
#include <kml/base/version.h>
#include <kml/base/uri_parser.h>
#include <cmath>
#include <iostream>
#include <link.h>
#include <memory>
#include <string>
static int providers(dl_phdr_info *info, size_t, void *) {
  if (info->dlpi_name && *info->dlpi_name && std::string(info->dlpi_name) != "linux-vdso.so.1")
    std::cout << "provider=" << info->dlpi_name << '\n';
  return 0;
}
static bool geometry(const std::string &xml) {
  std::string error;
  kmldom::ElementPtr root = kmldom::ParseNS(xml, &error);
  kmldom::KmlPtr kml = kmldom::AsKml(root);
  if (!kml || !error.empty()) return false;
  kmldom::PlacemarkPtr placemark = kmldom::AsPlacemark(kml->get_feature());
  if (!placemark || placemark->get_name() != "actual-point") return false;
  kmldom::PointPtr point = kmldom::AsPoint(placemark->get_geometry());
  if (!point || !point->has_coordinates() || point->get_coordinates()->get_coordinates_array_size()!=1) return false;
  const kmlbase::Vec3 v = point->get_coordinates()->get_coordinates_array_at(0);
  return std::abs(v.get_longitude()-12.5)<1e-12 && std::abs(v.get_latitude()+4.25)<1e-12 && std::abs(v.get_altitude()-123.0)<1e-12;
}
int main(int argc, char **argv) {
  if (argc != 2 || kmlbase::Version::GetString() != "1.3.0") return 1;
  const std::string xml = "<kml xmlns='http://www.opengis.net/kml/2.2'><Placemark><name>actual-point</name><Point><coordinates>12.5,-4.25,123</coordinates></Point></Placemark></kml>";
  if (!geometry(xml)) return 2;
  std::string error;
  if (kmldom::Parse("<kml><broken>", &error) || error.empty()) return 3;
  const std::string path = std::string(argv[1])+"/control.kmz";
  if (!kmlengine::KmzFile::WriteKmz(path.c_str(), xml)) return 4;
  kmlengine::KmzFilePtr zip = kmlengine::KmzFile::OpenFromFile(path.c_str());
  std::string decoded,missing,bytes;
  if (!zip || !zip->ReadKml(&decoded) || decoded != xml || !geometry(decoded)) return 5;
  if (zip->ReadFile("absent.kml", &missing) || !zip->SaveToString(&bytes) || bytes.empty()) return 6;
  kmlengine::KmzFilePtr memory = kmlengine::KmzFile::OpenFromString(bytes);
  decoded.clear();
  if (!memory || !memory->ReadKml(&decoded) || decoded != xml) return 7;
  if (kmlengine::KmzFile::OpenFromFile((std::string(argv[1])+"/missing.kmz").c_str())) return 8;
  if (kmlengine::KmzFile::OpenFromString("not a zip")) return 9;
  std::unique_ptr<kmlbase::UriParser> uri(kmlbase::UriParser::CreateResolvedUri("https://example.invalid/root/model.kml", "../other.kml"));
  std::string result;
  if (!uri || !uri->Normalize() || !uri->ToString(&result) || result!="https://example.invalid/other.kml") return 10;
  std::string filename;
  if (!kmlbase::UriParser::UriToFilename("file:///tmp/kml%20control.kml", &filename) || filename!="/tmp/kml control.kml") return 11;
  if (kmlbase::UriParser::CreateFromParse("http://[invalid")) return 12;
  std::cout << "kml_dom_coordinates_kmz_uri_negative_controls=true\n";
  dl_iterate_phdr(providers, nullptr);
  return 0;
}
