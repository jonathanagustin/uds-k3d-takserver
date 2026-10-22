#!/bin/bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Runs once, when the postgres entrypoint initialises an empty data
# directory. Creates template_postgis and loads the PostGIS extensions into it
# and into $POSTGRES_DB, the same set the previous image loaded.
#
# Keep this file mode 644. The entrypoint sources a .sh file that is not
# executable, and the psql array below is defined in that shell. An executable
# file runs as its own process, psql is empty there, and the container exits.
# shellcheck disable=SC2154
set -e

# The entrypoint defines psql as an array that connects as $POSTGRES_USER.
export PGUSER="${POSTGRES_USER}"

"${psql[@]}" <<- 'EOSQL'
CREATE DATABASE template_postgis IS_TEMPLATE true;
EOSQL

for DB in template_postgis "${POSTGRES_DB}"; do
    echo "Loading PostGIS extensions into ${DB}"
    "${psql[@]}" --dbname="${DB}" <<- 'EOSQL'
		CREATE EXTENSION IF NOT EXISTS postgis;
		CREATE EXTENSION IF NOT EXISTS postgis_topology;
		-- Reconnect so pg_settings picks up the new extension's defaults.
		\c
		CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
		CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder;
EOSQL
done
