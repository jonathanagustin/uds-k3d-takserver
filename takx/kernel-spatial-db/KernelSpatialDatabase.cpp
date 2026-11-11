/* Copyright 2026 uds-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only */
#include "db/SpatiaLiteDB.h"
#include "db/Cursor.h"
#include "db/Statement.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <sqlite3.h>
#include <spatialite.h>
#include <geos_c.h>
#include <proj_api.h>
#include <openssl/crypto.h>
#include <zlib.h>
using atakmap::db::SpatiaLiteDB;
using atakmap::db::Cursor;
static void require(bool ok) { if (!ok) throw std::runtime_error("real Kernel spatial database control failed"); }
static double number(SpatiaLiteDB &db, const char *sql) {
    std::unique_ptr<Cursor> c(db.query(sql)); require(c && c->moveToNext());
    require(!c->isNull(0)); double result = c->getDouble(0); require(!c->moveToNext()); return result;
}
int main(int argc, char **argv) {
    try {
        require(argc == 2);
        require(std::strcmp(spatialite_version(), "4.3.0a") == 0);
        require(std::strcmp(GEOSversion(), "3.4.3-CAPI-1.8.3 r4285") == 0);
        require(std::strcmp(sqlite3_libversion(), "3.45.3") == 0);
        require(std::strcmp(pj_get_release(), "Rel. 4.9.1, 04 March 2015") == 0);
        require(OpenSSL_version_num() == 0x30500090L);
        require(std::strcmp(zlibVersion(), "1.3.1") == 0 && std::strcmp(ZLIB_VERSION, "1.3.1") == 0);
        {
            SpatiaLiteDB db(argv[1]);
            require(number(db, "SELECT HasGeos()+HasProj()+HasIconv()+HasLibXML2()") == 4);
            require(number(db, "SELECT InitSpatialMetadata(1)") == 1);
            require(std::fabs(number(db, "SELECT Area(Intersection(GeomFromText('POLYGON((0 0,4 0,4 4,0 4,0 0))',4326),GeomFromText('POLYGON((2 2,6 2,6 6,2 6,2 2))',4326)))")-4) < 1e-12);
            require(std::fabs(number(db, "SELECT X(Transform(MakePoint(1,1,4326),3857))")-111319.49079327357) < 0.01);
            require(std::fabs(number(db, "SELECT Y(Transform(MakePoint(1,1,4326),3857))")-111325.1428663851) < 0.01);
            db.execute("CREATE TABLE typed(i INTEGER,t TEXT,r REAL)");
            db.beginTransaction();
            std::unique_ptr<atakmap::db::Statement> stmt(db.compileStatement("INSERT INTO typed VALUES(?,?,?)"));
            stmt->bind(1, 7); stmt->bind(2, "joined Kernel"); stmt->bind(3, 12.5); stmt->execute(); stmt.reset();
            db.setTransactionSuccessful(); db.endTransaction();
            db.beginTransaction(); db.execute("INSERT INTO typed VALUES(99,'rollback',0)"); db.endTransaction();
        }
        {
            SpatiaLiteDB db(argv[1]); std::unique_ptr<Cursor> c(db.query("SELECT i,t,r FROM typed"));
            require(c && c->moveToNext() && c->getInt(0)==7 && std::strcmp(c->getString(1),"joined Kernel")==0 && c->getDouble(2)==12.5 && !c->moveToNext());
            require(number(db,"SELECT HasGeos()+HasProj()+HasIconv()+HasLibXML2()") == 4);
        }
        puts("real_kernel_spatial_database_geometry_transform_typed_transaction_reopen=PASS");
        puts("legacy_api_crypto_acceptance=false modern_db2_sdk_jni_takx_acceptance=false");
        return 0;
    } catch (const std::exception &e) { std::fprintf(stderr,"%s\n",e.what()); return 2; }
}
