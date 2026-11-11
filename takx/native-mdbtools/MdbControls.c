/* Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only */
#include <mdbtools.h>
#include <stdio.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"failed line %d: %s\n",__LINE__,#x); return 1; } } while (0)
int main(int argc, char **argv) {
    CHECK(argc == 3);
    /* Header signature and real static link only; no OLE runtime claim. */
    size_t (*volatile ole_next)(MdbHandle *, MdbColumn *, void *) = mdb_ole_read_next;
    CHECK(ole_next != NULL);
    CHECK(strcmp(mdb_get_version(), "1.0.0") == 0);
    CHECK(mdb_open(argv[2], MDB_NOFLAGS) == NULL);
    MdbHandle *db = mdb_open(argv[1], MDB_NOFLAGS);
    CHECK(db != NULL);
    mdb_set_boolean_fmt_numbers(db);
    CHECK(mdb_read_catalog(db, MDB_TABLE) != NULL);
    MdbTableDef *table = mdb_read_table_by_name(db, "Customers", MDB_TABLE);
    CHECK(table != NULL);
    CHECK(mdb_read_columns(table) != NULL);
    char id[MDB_BIND_SIZE], contact[MDB_BIND_SIZE];
    int idlen = 0, contactlen = 0;
    CHECK(mdb_bind_column_by_name(table, "CustomerID", id, &idlen) > 0);
    CHECK(mdb_bind_column_by_name(table, "ContactName", contact, &contactlen) > 0);
    mdb_rewind_table(table);
    int rows = 0, alfki = 0;
    while (mdb_fetch_row(table)) {
        ++rows;
        if (!strcmp(id,"ALFKI")) { CHECK(!strcmp(contact,"Maria Anders")); ++alfki; }
    }
    CHECK(rows == 91 && alfki == 1);
    mdb_rewind_table(table);
    CHECK(mdb_fetch_row(table));
    mdb_free_tabledef(table);
    CHECK(mdb_read_table_by_name(db, "__missing_table__", MDB_TABLE) == NULL);
    mdb_close(db);
    printf("mdbtools=1.0.0\ncustomers=91\nalfki=Maria Anders\nreal_mdb_catalog_rows_and_missing_controls=true\n");
    return 0;
}
