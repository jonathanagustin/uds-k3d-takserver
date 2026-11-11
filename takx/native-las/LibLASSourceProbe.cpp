// Copyright 2026 uds-takserver authors
// SPDX-License-Identifier: GPL-3.0-only
#ifdef NDEBUG
#error Source probe assertions must remain enabled
#endif
#include <liblas/liblas.hpp>
#include <liblas/capi/liblas.h>
#include <liblas/version.hpp>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>
#include <vector>
#include <dlfcn.h>
#include <limits.h>
#include <cstdlib>

struct Expected {
    double x, y, z, time;
    uint16_t intensity;
    uint8_t classification;
    uint16_t red, green, blue;
};
static const Expected points[] = {
    {500001.25,4100002.50,100.75,123456.5,23,2,65535,1,22},
    {499999.25,4099990.50,99.25,123457.5,65535,5,0,65535,123},
    {500003.00,4100003.75,-12.50,0.0,0,1,1122,3355,6599}
};
static bool near(double a,double b) { return std::abs(a-b)<0.001; }
static std::vector<char> bytes(const std::string &path) {
    std::ifstream stream(path.c_str(),std::ios::binary);
    return std::vector<char>((std::istreambuf_iterator<char>(stream)),{});
}
static void loaded(const char *name,void *symbol) {
    Dl_info info;assert(dladdr(symbol,&info));char canonical[PATH_MAX];
    assert(realpath(info.dli_fname,canonical));std::cout << name << '=' << canonical << '\n';
}
static void check_cpp(const liblas::Point &p,const Expected &e) {
    assert(near(p.GetX(),e.x) && near(p.GetY(),e.y) && near(p.GetZ(),e.z));
    assert(std::abs(p.GetTime()-e.time)<1e-9 && p.GetIntensity()==e.intensity);
    assert(p.GetClassification().GetClass()==e.classification);
    assert(p.GetReturnNumber()==1 && p.GetNumberOfReturns()==1);
    liblas::Color color=p.GetColor();assert(color.GetRed()==e.red && color.GetGreen()==e.green && color.GetBlue()==e.blue);
}
static void check_c(LASPointH p,const Expected &e) {
    assert(near(LASPoint_GetX(p),e.x) && near(LASPoint_GetY(p),e.y) && near(LASPoint_GetZ(p),e.z));
    assert(std::abs(LASPoint_GetTime(p)-e.time)<1e-9 && LASPoint_GetIntensity(p)==e.intensity);
    assert(LASPoint_GetClassification(p)==e.classification);
    assert(LASPoint_GetReturnNumber(p)==1 && LASPoint_GetNumberOfReturns(p)==1);
    unsigned short rgb[3];assert(LASPoint_GetColorRGB(p,rgb)==LE_None);
    assert(rgb[0]==e.red && rgb[1]==e.green && rgb[2]==e.blue);
}
static void run(const std::string &base,bool compressed) {
    const std::string path=base+(compressed?"/roundtrip.laz":"/roundtrip.las");
    std::cerr << "phase=header,compressed=" << compressed << "\n";
    liblas::Header header;header.SetVersionMajor(1);header.SetVersionMinor(2);
    header.SetDataFormatId(liblas::ePointFormat3);header.SetScale(0.01,0.01,0.01);
    header.SetOffset(500000,4100000,0);header.SetPointRecordsCount(3);header.SetCompressed(compressed);
    header.SetMin(499999.25,4099990.50,-12.50);header.SetMax(500003,4100003.75,100.75);
    {
        std::ofstream out(path.c_str(),std::ios::binary);assert(out.good());
        std::cerr << "phase=writer\n";liblas::Writer writer(out,header);
        std::cerr << "phase=write-points\n";for(const auto &e:points) {
            liblas::Point p(&header);p.SetCoordinates(e.x,e.y,e.z);p.SetTime(e.time);
            p.SetIntensity(e.intensity);p.SetClassification(e.classification);
            p.SetReturnNumber(1);p.SetNumberOfReturns(1);p.SetColor(liblas::Color(e.red,e.green,e.blue));
            assert(writer.WritePoint(p));
        }
    }
    std::cerr << "phase=read-cpp\n";uint32_t offset=0;
    {
        std::ifstream input(path.c_str(),std::ios::binary);liblas::ReaderFactory factory;
        liblas::Reader reader=factory.CreateWithStream(input);
        const auto &h=reader.GetHeader();assert(h.Compressed()==compressed && h.GetPointRecordsCount()==3);
        assert(h.GetDataFormatId()==liblas::ePointFormat3 && near(h.GetScaleX(),0.01) && near(h.GetOffsetY(),4100000));
        offset=h.GetDataOffset();unsigned count=0;
        while(reader.ReadNextPoint()){assert(count<3);check_cpp(reader.GetPoint(),points[count++]);}
        assert(count==3);
        for(unsigned index: {0u,2u,0u}){assert(reader.Seek(index));assert(reader.ReadNextPoint());check_cpp(reader.GetPoint(),points[index]);}
        reader.Reset();assert(reader.ReadNextPoint());check_cpp(reader.GetPoint(),points[0]);
        reader.Reset();count=0;while(reader.ReadNextPoint()){check_cpp(reader.GetPoint(),points[count++]);}assert(count==3);
        reader.Reset();assert(reader.ReadNextPoint());check_cpp(reader.GetPoint(),points[0]);
        assert(reader.ReadPointAt(2));check_cpp(reader.GetPoint(),points[2]);
        assert(reader.ReadPointAt(0));check_cpp(reader.GetPoint(),points[0]);
        assert(!reader.Seek(3));bool outside=false;try{reader.Seek(999);}catch(const std::exception &){outside=true;}assert(outside);
        assert(reader.Seek(0));assert(reader.ReadNextPoint());check_cpp(reader.GetPoint(),points[0]);
    }
    const auto file=bytes(path);assert(file.size()>offset+1 && std::string(file.data(),4)=="LASF");
    assert(static_cast<unsigned char>(file.at(104))==(compressed?131:3));
    if(compressed)assert(std::string(file.begin(),file.end()).find("laszip encoded")!=std::string::npos);
    std::cerr << "phase=read-c-api\n";LASError_Reset();LASReaderH reader=LASReader_Create(path.c_str());assert(reader);
    LASHeaderH h=LASReader_GetHeader(reader);assert(h && LASHeader_GetPointRecordsCount(h)==3);
    assert(LASHeader_Compressed(h)==static_cast<int>(compressed) && LASHeader_GetDataFormatId(h)==3);
    assert(near(LASHeader_GetScaleX(h),0.01) && near(LASHeader_GetScaleY(h),0.01) && near(LASHeader_GetScaleZ(h),0.01));
    assert(near(LASHeader_GetOffsetX(h),500000) && near(LASHeader_GetOffsetY(h),4100000) && near(LASHeader_GetOffsetZ(h),0));
    LASHeader_Destroy(h);
    unsigned count=0;while(LASPointH point=LASReader_GetNextPoint(reader)){assert(count<3);check_c(point,points[count++]);}
    assert(count==3);
    assert(LASReader_Seek(reader,2)==LE_None);check_c(LASReader_GetNextPoint(reader),points[2]);
    assert(LASReader_Seek(reader,0)==LE_None);check_c(LASReader_GetNextPoint(reader),points[0]);
    assert(LASReader_Seek(reader,3)==LE_Failure);LASError_Reset();
    assert(LASReader_Seek(reader,999)==LE_Failure);assert(LASError_GetErrorCount()>0);
    std::cout << "c_api_seek_exception_returns_failure_with_error_stack=true\n";LASError_Reset();
    assert(LASReader_Seek(reader,0)==LE_None);check_c(LASReader_GetNextPoint(reader),points[0]);
    LASReader_Destroy(reader);
    const std::string truncated=path+".truncated";
    {std::ofstream output(truncated.c_str(),std::ios::binary);output.write(file.data(),offset+1);}
    std::cerr << "phase=truncated-cpp\n";bool rejected=false,exception_seen=false;count=0;
    try {
        std::ifstream input(truncated.c_str(),std::ios::binary);liblas::ReaderFactory factory;
        liblas::Reader broken=factory.CreateWithStream(input);
        while(broken.ReadNextPoint()){++count;assert(count<=3);}
        rejected=count!=3;
    } catch(const std::exception &) {rejected=true;exception_seen=true;}
    assert(rejected);if(compressed)assert(count==0 && exception_seen);else std::cout << "existing_truncated_las_partial_points=" << count << "\n";
    std::cerr << "phase=truncated-c-api\n";LASError_Reset();reader=LASReader_Create(truncated.c_str());count=0;
    if(reader){while(LASReader_GetNextPoint(reader)){++count;assert(count<=3);}LASReader_Destroy(reader);}
    if(compressed){assert(count==0);assert(LASError_GetErrorCount()>0);}LASError_Reset();
    std::cout << (compressed?"laz":"las") << "_semantic_roundtrip=pass;points=3;payload_truncation_rejected=true\n";
}
int main(int argc,char **argv) {
    assert(argc==2 || argc==3);std::cout.setf(std::ios::unitbuf);std::cerr << "phase=provenance\n";loaded("loaded_liblas",reinterpret_cast<void*>(&liblas::GetVersion));
    loaded("loaded_liblas_c",reinterpret_cast<void*>(&LAS_GetVersion));
    char *version=LAS_GetVersion();assert(version);std::cout << "internal_version=" << version << '\n';LASString_Free(version);
    run(argv[1],false);run(argv[1],true);
    if(argc==3) {
        std::cerr << "phase=immutable-original-laz-truncation\n";
        bool rejected=false,exception_seen=false;unsigned count=0;
        try {
            std::ifstream in(argv[2],std::ios::binary);liblas::ReaderFactory factory;
            liblas::Reader reader=factory.CreateWithStream(in);
            while(reader.ReadNextPoint()){++count;assert(count<=3);}
            rejected=count!=3;
        } catch(const std::exception &) {rejected=true;exception_seen=true;}
        assert(rejected && count==0 && exception_seen);LASError_Reset();LASReaderH reader=LASReader_Create(argv[2]);count=0;
        if(reader){while(LASReader_GetNextPoint(reader)){++count;assert(count<=3);}LASReader_Destroy(reader);}
        assert(count==0);assert(LASError_GetErrorCount()>0);LASError_Reset();
        std::cerr << "phase=malformed-laz-failed-seek\n";
        bool seek_failed=false;
        {std::ifstream in(argv[2],std::ios::binary);liblas::ReaderFactory factory;
         liblas::Reader broken=factory.CreateWithStream(in);
         try {seek_failed=!broken.Seek(2);}catch(const std::exception &){seek_failed=true;}}
        assert(seek_failed);LASError_Reset();reader=LASReader_Create(argv[2]);assert(reader);
        assert(LASReader_Seek(reader,2)==LE_Failure);assert(LASError_GetErrorCount()>0);
        LASReader_Destroy(reader);LASError_Reset();
        std::cout << "immutable_original_truncated_laz_rejected_by_cpp_and_c=true\n";
    }
}
