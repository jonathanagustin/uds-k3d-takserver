# 1. Record architecture decisions

Date: 2026-10-18

## Status

Accepted

## Context

This package deploys TAK Server on UDS. The chart values, the gateway, the certificates, and the metrics choice all need a place that is more durable than a pull request.

## Decision

We will use Architecture Decision Records, as described by Michael Nygard, in `adr/`. `.adr-dir` points at that directory. New decisions get the next number, a date, a status, the context, the decision, and the consequences.

## Consequences

`docs/configuration.md`, `docs/networking.md`, and `docs/sso.md` stay the operator-facing notes. The ADRs record why those notes look the way they do.
