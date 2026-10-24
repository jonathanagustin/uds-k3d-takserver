// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// Adds the init container that renders the OIDC client secret and the
// keystore password into CoreConfig.xml. It is applied when a TAK pod is
// created, so no TAK pod can
// start with the unrendered template. A node that did would publish that
// copy to the others through the Ignite configuration cache.

export const NAMESPACE = "takserver";

// Pods that read CoreConfig.xml. Ignite, NATS and Postgres do not.
export const TAK_APPS = [
  "takserver-config",
  "takserver-messaging",
  "takserver-api",
  "takserver-plugins",
];

export const RELOAD_LABEL = "uds.dev/oidc-reload";
export const RELOAD_VALUE = "takserver";
export const INIT_NAME = "render-oidc";
export const CONFIG_MOUNT = "rendered-core";

interface Volume {
  name: string;
  [key: string]: unknown;
}

interface Container {
  name: string;
  image?: string;
  volumeMounts?: { name: string; mountPath: string; readOnly?: boolean }[];
  [key: string]: unknown;
}

export interface PodLike {
  metadata?: { labels?: Record<string, string>; namespace?: string };
  spec?: {
    containers?: Container[];
    initContainers?: Container[];
    volumes?: Volume[];
  };
}

export function isTakPod(pod: PodLike): boolean {
  const app = pod.metadata?.labels?.app;
  return app !== undefined && TAK_APPS.includes(app);
}

function renderVolumes(): Volume[] {
  return [
    { name: CONFIG_MOUNT, emptyDir: {} },
    { name: "oidc-script", configMap: { name: "takserver-oidc-render" } },
    { name: "oidc-template", configMap: { name: "core-config" } },
    { name: "oidc-secret", secret: { secretName: "takserver-sso" } },
    { name: "keystore-secret", secret: { secretName: "takserver-keystore" } },
  ];
}

function renderInit(image: string): Container {
  return {
    name: INIT_NAME,
    image,
    imagePullPolicy: "IfNotPresent",
    command: ["bash", "/scripts/render-oidc.sh"],
    volumeMounts: [
      { name: "oidc-script", mountPath: "/scripts", readOnly: true },
      { name: "oidc-template", mountPath: "/template", readOnly: true },
      { name: "oidc-secret", mountPath: "/var/run/tak-sso", readOnly: true },
      { name: "keystore-secret", mountPath: "/var/run/tak-keystore", readOnly: true },
      { name: CONFIG_MOUNT, mountPath: "/conf" },
    ],
    resources: {
      requests: { cpu: "20m", memory: "64Mi" },
      limits: { cpu: "200m", memory: "128Mi" },
    },
  };
}

// Mutates the pod in place. Safe to call twice: every addition is keyed by
// name and skipped when present. Returns true when the pod was changed.
export function addRender(pod: PodLike, image: string): boolean {
  if (!isTakPod(pod)) {
    return false;
  }
  const spec = (pod.spec ??= {});
  let changed = false;

  const volumes = (spec.volumes ??= []);
  for (const volume of renderVolumes()) {
    if (!volumes.some(existing => existing.name === volume.name)) {
      volumes.push(volume);
      changed = true;
    }
  }

  // Appended after any init container the Deployment already has, so
  // wait-deps keeps running first.
  const inits = (spec.initContainers ??= []);
  if (!inits.some(existing => existing.name === INIT_NAME)) {
    inits.push(renderInit(image));
    changed = true;
  }

  const main = spec.containers?.[0];
  if (main) {
    const mounts = (main.volumeMounts ??= []);
    if (!mounts.some(existing => existing.name === CONFIG_MOUNT)) {
      mounts.push({ name: CONFIG_MOUNT, mountPath: "/conf" });
      changed = true;
    }
  }

  const metadata = (pod.metadata ??= {});
  const labels = (metadata.labels ??= {});
  if (labels[RELOAD_LABEL] !== RELOAD_VALUE) {
    labels[RELOAD_LABEL] = RELOAD_VALUE;
    changed = true;
  }
  return changed;
}
