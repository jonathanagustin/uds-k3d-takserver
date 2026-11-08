// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Preload for `node --import`. start.sh puts that flag in NODE_OPTIONS.
// Node applies NODE_OPTIONS before the entry module and does not copy those
// flags into process.execArgv, so this file installs on load. It does not
// look at execArgv.

import TAK from '@tak-ps/node-tak';

import { install } from './tak-error-guard.mjs';

install(TAK);
