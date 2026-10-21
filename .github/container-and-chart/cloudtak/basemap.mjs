// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Default basemap: the shared settings and the nginx tile proxy.
//
// CloudTAK fetches remote tiles in its API process and refuses private and
// mesh addresses, so a tile host behind the mesh egress gateway cannot be
// reached that way. Instead nginx in the CloudTAK container proxies
// /uds-basemap/tiles/{z}/{x}/{y} to BASEMAP_URL:
//
// - Only signed-in users get tiles. A subrequest checks the CloudTAK session
//   token that the web client adds to tile URLs on its own host.
// - Requests to the tile host carry an identifying User-Agent and the
//   browser's Referer, and none of the browser's other headers or cookies.
// - Each session is held to BASEMAP_RATE tiles a second after a burst of
//   BASEMAP_BURST, which a map view stays inside and bulk download does not.
// - Tiles are cached on disk, following the tile host's cache headers, or 7
//   days when it sends none.
// - Zoom levels above BASEMAP_MAXZOOM are refused.
//
// `node basemap.mjs nginx <dir>` writes, for start.sh:
//   http.conf      cache zones and the token map (http block)
//   server.conf    the /uds-basemap/ locations (server block)
//   tilejson.json  TileJSON for the CloudTAK basemap record
//
// bootstrap.mjs calls reconcile() to keep the basemap record in step.

import fs from 'node:fs';
import path from 'node:path';

// Path the managed basemap's tiles are served under. bootstrap.mjs finds the
// record it owns by this path in its url.
export const TILE_PATH = '/uds-basemap/tiles';
// CloudTAK fetches this TileJSON from its own nginx. The host must be
// "localhost": CloudTAK skips its private address check only for that host.
export const TILEJSON_URL = 'http://localhost:5000/uds-basemap/tilejson.json';

const env = (name, fallback) => {
    const value = process.env[name] ?? fallback;
    if (value === undefined || value === '') throw new Error(`${name} is not set`);
    return value;
};

const zoom = (name, fallback) => {
    const value = Number(env(name, fallback));
    if (!Number.isInteger(value) || value < 0 || value > 24) throw new Error(`${name} must be an integer from 0 to 24`);
    return value;
};

// Every value below goes into a double-quoted nginx string, where ", \, and
// $ (a variable) are special. Control characters would end the line.
function safe(name, value) {
    if (/["\\$\u0000-\u001f\u007f]/.test(value)) throw new Error(`${name} must not contain ", \\, $, or control characters`);
    return value;
}

// BASEMAP_ENABLED is "true", "false", or unset. Unset means an older chart:
// leave basemaps alone.
export function mode() {
    const value = process.env.BASEMAP_ENABLED;
    if (value === undefined || value === '') return 'unmanaged';
    if (value === 'true') return 'enabled';
    if (value === 'false') return 'disabled';
    throw new Error('BASEMAP_ENABLED must be true or false');
}

// These are written unquoted.
function count(name, fallback) {
    const value = env(name, fallback);
    if (!/^[1-9][0-9]{0,5}$/.test(value)) throw new Error(`${name} must be a positive integer`);
    return value;
}

function size(value) {
    if (!/^[0-9]+[kmg]?$/.test(value)) throw new Error('BASEMAP_CACHE_SIZE must be a size such as 256m');
    return value;
}

function file(value) {
    if (!/^\/[A-Za-z0-9._/-]+$/.test(value)) throw new Error('BASEMAP_CA_FILE must be an absolute path');
    if (!fs.existsSync(value)) throw new Error(`BASEMAP_CA_FILE ${value} does not exist`);
    return value;
}

export function settings() {
    const upstream = env('BASEMAP_URL');
    for (const p of ['{z}', '{x}', '{y}']) {
        if (!upstream.includes(p)) throw new Error(`BASEMAP_URL must contain ${p}`);
    }
    const rest = upstream.replace(/\{[zxy]\}/g, '');
    safe('BASEMAP_URL without {z}, {x}, {y}', rest);
    const parsed = new URL(upstream.replace(/\{([zxy])\}/g, '0'));
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') throw new Error('BASEMAP_URL must be http or https');
    if (parsed.username || parsed.password) throw new Error('BASEMAP_URL must not carry credentials');

    const publicUrl = new URL(env('BASEMAP_PUBLIC_URL'));
    if (publicUrl.protocol !== 'https:' && publicUrl.protocol !== 'http:') throw new Error('BASEMAP_PUBLIC_URL must be http or https');

    const minzoom = zoom('BASEMAP_MINZOOM', '0');
    const maxzoom = zoom('BASEMAP_MAXZOOM', '19');
    if (minzoom > maxzoom) throw new Error('BASEMAP_MINZOOM is above BASEMAP_MAXZOOM');

    return {
        name: env('BASEMAP_NAME', 'OpenStreetMap'),
        upstream,
        host: parsed.host,
        hostname: parsed.hostname,
        protocol: parsed.protocol,
        publicOrigin: publicUrl.origin,
        tiles: `${publicUrl.origin}${TILE_PATH}/{z}/{x}/{y}`,
        attribution: env('BASEMAP_ATTRIBUTION', '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'),
        minzoom,
        maxzoom,
        userAgent: safe('BASEMAP_USER_AGENT', env('BASEMAP_USER_AGENT')),
        rate: count('BASEMAP_RATE', '20'),
        burst: count('BASEMAP_BURST', '200'),
        cacheSize: size(env('BASEMAP_CACHE_SIZE', '256m')),
        caFile: file(env('BASEMAP_CA_FILE', '/etc/ssl/certs/ca-certificates.crt')),
    };
}

// nginx wants a literal resolver. Use the pod's.
function resolvers() {
    const conf = fs.readFileSync('/etc/resolv.conf', 'utf8');
    const servers = [...conf.matchAll(/^nameserver\s+(\S+)/gm)].map((m) => (m[1].includes(':') ? `[${m[1]}]` : m[1]));
    if (!servers.length) throw new Error('no nameserver in /etc/resolv.conf');
    return servers.join(' ');
}

export function tilejson(s) {
    return {
        tilejson: '3.0.0',
        version: '1.0.0',
        scheme: 'xyz',
        name: s.name,
        description: '',
        attribution: s.attribution,
        tileSize: 256,
        minzoom: s.minzoom,
        maxzoom: s.maxzoom,
        tiles: [s.tiles],
        bounds: [-180, -85.0511, 180, 85.0511],
        center: [0, 0, 2],
        type: 'raster',
    };
}

export function httpConf(s, dir) {
    return `
    # Default basemap (basemap.mjs)
    proxy_cache_path ${dir}/cache levels=1:2 keys_zone=uds_basemap:10m max_size=${s.cacheSize} inactive=7d use_temp_path=off;
    proxy_cache_path ${dir}/auth levels=1 keys_zone=uds_basemap_auth:1m max_size=16m inactive=5m use_temp_path=off;
    map $request_uri $uds_basemap_token {
        "~[?&]token=(?<t>[A-Za-z0-9._~-]+)" $t;
        default "";
    }
    # The browser's Referer goes to the tile host unchanged. Without one,
    # name the site.
    map $http_referer $uds_basemap_referer {
        "" "${s.publicOrigin}/";
        default $http_referer;
    }
    # Per session. A map view loads tens of tiles at once; a scraper keeps
    # going.
    limit_req_zone $uds_basemap_token zone=uds_basemap_rate:1m rate=${s.rate}r/s;
`;
}

export function serverConf(s, dir) {
    const zooms = Array.from({ length: s.maxzoom - s.minzoom + 1 }, (_, i) => s.minzoom + i).join('|');
    const target = s.upstream.replace(/\{([zxy])\}/g, '${uds_$1}');
    const tls = s.protocol === 'https:' ? `
            proxy_ssl_server_name on;
            proxy_ssl_name ${s.hostname};
            proxy_ssl_verify on;
            proxy_ssl_verify_depth 4;
            proxy_ssl_trusted_certificate ${s.caFile};` : '';
    return `
        # Default basemap (basemap.mjs)
        location ^~ /uds-basemap/ {
            location = /uds-basemap/tilejson.json {
                allow 127.0.0.1;
                allow ::1;
                deny all;
                default_type application/json;
                add_header 'Cache-Control' 'no-store' always;
                alias ${dir}/tilejson.json;
            }

            location ~ "^${TILE_PATH}/(?<uds_z>${zooms})/(?<uds_x>[0-9]{1,8})/(?<uds_y>[0-9]{1,8})$" {
                limit_except GET { deny all; }
                auth_request /_uds_basemap_auth;
                limit_req zone=uds_basemap_rate burst=${s.burst} nodelay;
                limit_req_status 429;

                resolver ${resolvers()} valid=300s ipv6=off;
                resolver_timeout 5s;
                set $uds_basemap_upstream "${target}";
                proxy_pass $uds_basemap_upstream;
                proxy_http_version 1.1;

                # Send only these headers to the tile host.
                proxy_pass_request_headers off;
                proxy_set_header Host "${s.host}";
                proxy_set_header Connection "";
                proxy_set_header User-Agent "${s.userAgent}";
                proxy_set_header Referer $uds_basemap_referer;
                proxy_set_header Accept "image/avif,image/webp,image/png,image/*;q=0.8";
${tls}
                proxy_connect_timeout 10s;
                proxy_read_timeout 30s;

                proxy_cache uds_basemap;
                proxy_cache_key "$uds_z/$uds_x/$uds_y";
                proxy_cache_valid 200 7d;
                proxy_cache_valid 404 1h;
                proxy_cache_lock on;
                proxy_cache_revalidate on;
                proxy_cache_background_update on;
                proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
                proxy_ignore_headers Set-Cookie;
                proxy_hide_header Set-Cookie;

                add_header 'X-Content-Type-Options' 'nosniff' always;
                add_header 'X-Cache-Status' $upstream_cache_status always;
            }

            return 404;
        }

        location = /_uds_basemap_auth {
            internal;
            proxy_pass http://127.0.0.1:5001/api/profile/video?limit=1;
            proxy_pass_request_body off;
            proxy_pass_request_headers off;
            proxy_set_header Content-Length "";
            proxy_set_header Authorization "Bearer $uds_basemap_token";
            proxy_cache uds_basemap_auth;
            proxy_cache_key "$uds_basemap_token";
            proxy_cache_valid 200 60s;
            proxy_ignore_headers Cache-Control Expires Set-Cookie;
        }
`;
}

const ownBasemap = (b) => {
    try {
        return !b.username && new URL(b.url).pathname.startsWith(`${TILE_PATH}/`);
    } catch {
        return false;
    }
};

async function setDefault(api, id, onlyIf) {
    const current = (await api('/api/config?keys=map::basemap'))['map::basemap'] ?? null;
    if (onlyIf !== undefined && !onlyIf.includes(current)) return;
    if (current === id) return;
    await api('/api/config', { method: 'PUT', body: { 'map::basemap': id } });
}

// Keep the server basemap this chart owns in step with the settings.
// `api(path, opts)` calls CloudTAK as its administrator and returns the
// parsed body.
export async function reconcile(api) {
    const m = mode();
    if (m === 'unmanaged') return 'not managed';

    const list = await api('/api/basemap?impersonate=true&scope=server&hidden=all&type=raster&sort=id&order=asc&limit=100');
    const owned = list.items.filter(ownBasemap);

    if (m === 'disabled') {
        await setDefault(api, null, owned.map((b) => b.id));
        for (const b of owned) await api(`/api/basemap/${b.id}`, { method: 'DELETE' });
        return owned.length ? `off, deleted ${owned.map((b) => b.id).join(', ')}` : 'off';
    }

    const s = settings();
    const want = {
        name: s.name,
        url: s.tiles,
        attribution: s.attribution,
        minzoom: s.minzoom,
        maxzoom: s.maxzoom,
        hidden: false,
        overlay: false,
        sharing_enabled: false,
    };
    const fixed = {
        scope: 'server',
        protocol: 'zxy',
        type: 'raster',
        format: 'png',
        tilesize: 256,
        tilejson: TILEJSON_URL,
    };

    let [record, ...extra] = owned;
    let action = 'unchanged';
    if (!record) {
        record = await api('/api/basemap', { method: 'POST', body: { ...want, ...fixed } });
        action = 'created';
    } else if (Object.entries(want).some(([k, v]) => record[k] !== v)) {
        record = await api(`/api/basemap/${record.id}`, { method: 'PATCH', body: { ...want, ...fixed } });
        action = 'updated';
    }
    for (const b of extra) await api(`/api/basemap/${b.id}`, { method: 'DELETE' });

    if ((process.env.BASEMAP_DEFAULT || 'true') === 'true') await setDefault(api, record.id);
    return `${s.name} (${record.id}) ${action}`;
}

if (process.argv[2] === 'nginx') {
    const dir = process.argv[3];
    const s = settings();
    fs.mkdirSync(path.join(dir, 'cache'), { recursive: true });
    fs.mkdirSync(path.join(dir, 'auth'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'http.conf'), httpConf(s, dir));
    fs.writeFileSync(path.join(dir, 'server.conf'), serverConf(s, dir));
    fs.writeFileSync(path.join(dir, 'tilejson.json'), JSON.stringify(tilejson(s)));
    console.log(`basemap: ${s.name} from ${s.host}, zoom ${s.minzoom}-${s.maxzoom}`);
}
