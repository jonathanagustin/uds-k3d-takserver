// Copyright 2026 uds-k3d-takserver authors
// SPDX-License-Identifier: GPL-3.0-only

// TakClient custom resource. Scaffolded with `npx pepr crd create` and turned
// into crds/takclient.yaml with `npx pepr crd generate`. See ADR 22.
// Kind: TakClient
// Group: tak
// Version: v1alpha1
// Domain: jonathanagustin.github.io

export interface TakClientSpec {
  /**
   * Certificate CN and TAK file user name. At least 4 characters: letters, numbers, dots, underscores, and hyphens.
   */
  callsign: string;

  /**
   * TAK groups the client is in, for example Operators.
   */
  groups: string[];

  /**
   * Certificate lifetime in days. Default 30, maximum 365.
   */
  validityDays?: number;
}

export interface TakClientStatus {
  conditions: TakClientStatusCondition[];
  /**
   * Certificate serial number, hex.
   */
  serialNumber?: string;
  /**
   * SHA-256 fingerprint of the certificate, colon-separated hex.
   */
  fingerprint?: string;
  /**
   * Certificate expiry, RFC 3339.
   */
  notAfter?: string;
  /**
   * Secret in the same namespace with the certificate, the key, and the data package.
   */
  secretName?: string;
  /**
   * metadata.generation the status was written for.
   */
  observedGeneration?: number;
}

export const details = {
  plural: "takclients",
  scope: "Namespaced",
  shortName: "takc",
};

type TakClientStatusCondition = {
  /**
   * lastTransitionTime is the last time the condition transitioned from one status to another.
   */
  lastTransitionTime: Date;
  /**
   * message is a human readable message indicating details about the transition. This may be an empty string.
   */
  message: string;
  /**
   * observedGeneration is the .metadata.generation the condition was set for.
   */
  observedGeneration?: number;
  /**
   * reason is a CamelCase identifier for the condition's last transition.
   */
  reason: string;
  /**
   * status of the condition, one of True, False, Unknown.
   */
  status: string;
  /**
   * type of the condition, for example Ready.
   */
  type: string;
};
