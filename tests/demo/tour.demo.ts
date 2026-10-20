/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// Web UI walkthrough for the demo video: Keycloak SSO through UDS Core,
// then the TAK admin pages. The waits and mouse paths are for the viewer.
// Writes .playwright/demo/events.json so demo/assemble.sh can time the zoom
// and the captions.
import { mkdirSync, writeFileSync } from "node:fs";

import { expect, type Locator, type Page, test } from "@playwright/test";

const takUrl = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";
const username = process.env.KEYCLOAK_USER || "doug";
const password = process.env.KEYCLOAK_PASSWORD || "unicorn123!@#UN";

const events: { kind: string; at: number; value: string }[] = [];
let startedAt = Date.now();
let mouse = { x: 640, y: 420 };

function mark(kind: string, value: string) {
  events.push({ kind, at: (Date.now() - startedAt) / 1000, value });
}

// A visible cursor and a ring on each click. Headless video has no pointer.
const pointerOverlay = () => {
  const install = () => {
    // Frames get their own document. One cursor, in the top page only.
    if (window.top !== window || document.getElementById("demo-cursor")) {
      return;
    }
    const style = document.createElement("style");
    style.textContent = `
      #demo-cursor { position: fixed; z-index: 2147483647; pointer-events: none;
        width: 30px; height: 30px; margin: -4px 0 0 -4px; left: var(--x, 640px); top: var(--y, 420px); }
      #demo-cursor svg { filter: drop-shadow(0 1px 2px rgba(0,0,0,.5)); }
      .demo-ripple { position: fixed; z-index: 2147483646; pointer-events: none;
        width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%;
        border: 3px solid #cba6f7; animation: demo-ripple .6s ease-out forwards; }
      @keyframes demo-ripple { from { transform: scale(.3); opacity: 1 } to { transform: scale(1.4); opacity: 0 } }`;
    document.head.appendChild(style);
    const cursor = document.createElement("div");
    cursor.id = "demo-cursor";
    cursor.innerHTML =
      '<svg width="30" height="30" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 13.8 L10.6 20 L13.2 18.8 L10.2 12.6 L16.4 12.4 Z" fill="#ffffff" stroke="#11111b" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cursor);
    const saved = sessionStorage.getItem("demo-cursor");
    if (saved) {
      const [x, y] = saved.split(",");
      cursor.style.setProperty("--x", `${x}px`);
      cursor.style.setProperty("--y", `${y}px`);
    }
    document.addEventListener(
      "mousemove",
      (event) => {
        cursor.style.setProperty("--x", `${event.clientX}px`);
        cursor.style.setProperty("--y", `${event.clientY}px`);
        sessionStorage.setItem("demo-cursor", `${event.clientX},${event.clientY}`);
      },
      true,
    );
    document.addEventListener(
      "mousedown",
      (event) => {
        const ring = document.createElement("div");
        ring.className = "demo-ripple";
        ring.style.left = `${event.clientX}px`;
        ring.style.top = `${event.clientY}px`;
        document.body.appendChild(ring);
        setTimeout(() => ring.remove(), 700);
      },
      true,
    );
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install);
  } else {
    install();
  }
};

// Captions are not drawn in the page. demo/assemble.sh draws them in a band
// below the recorded area, so they never cover the UI.
function caption(text: string) {
  mark("caption", text);
}

// Seeded, so every recording types with the same rhythm.
let seed = 0x7a4b;
function random() {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

function between(low: number, high: number) {
  return Math.round(low + random() * (high - low));
}

// Uneven typing: 50-220 ms per key, with a short pause now and then.
async function typeLikeAPerson(page: Page, text: string) {
  for (const key of text) {
    await page.keyboard.type(key);
    await page.waitForTimeout(between(50, 220));
    if (random() < 0.2) {
      await page.waitForTimeout(between(150, 450));
    }
  }
}

async function glideTo(page: Page, target: Locator) {
  const box = await target.boundingBox();
  if (!box) {
    return;
  }
  const x = box.x + Math.min(box.width / 2, 60);
  const y = box.y + box.height / 2;
  await page.mouse.move(mouse.x, mouse.y);
  await page.mouse.move(x, y, { steps: 28 });
  mouse = { x, y };
  await page.waitForTimeout(250);
}

async function clickLikeAPerson(page: Page, target: Locator) {
  await glideTo(page, target);
  await page.mouse.down();
  await page.waitForTimeout(90);
  await page.mouse.up();
}

async function visit(page: Page, path: string, label: string, hold = 3_000) {
  const response = await page.goto(new URL(path, takUrl).toString(), {
    waitUntil: "load",
    timeout: 60_000,
  });
  expect(response?.status() ?? 0, `${path} status`).toBeLessThan(400);
  await page.mouse.move(mouse.x, mouse.y);
  caption(label);
  await page.waitForTimeout(hold);
}

function saveEvents() {
  mkdirSync(".playwright/demo", { recursive: true });
  writeFileSync(".playwright/demo/events.json", JSON.stringify(events, null, 2));
}

test("TAK web UI through UDS Core SSO", async ({ page }) => {
  test.setTimeout(300_000);
  try {
    await walkthrough(page);
  } finally {
    saveEvents();
  }
});

async function walkthrough(page: Page) {
  startedAt = Date.now();
  page.on("dialog", (dialog) => dialog.accept());
  await page.addInitScript(pointerOverlay);

  await page.goto(takUrl);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });
  const userField = page.getByLabel("Username or email");
  await expect(userField).toBeVisible();
  await page.mouse.move(mouse.x, mouse.y);
  caption("TAK redirects to Keycloak (UDS Core SSO)");
  await page.waitForTimeout(2_000);
  caption("Sign in with a demo Keycloak account");

  await clickLikeAPerson(page, userField);
  await typeLikeAPerson(page, username);
  await page.waitForTimeout(400);
  const passwordField = page.getByLabel("Password");
  await clickLikeAPerson(page, passwordField);
  await typeLikeAPerson(page, password);
  await page.waitForTimeout(500);
  await clickLikeAPerson(page, page.getByRole("button", { name: "Sign In" }));

  // /UDS Core/Admin maps to ROLE_ADMIN, so TAK opens the Marti admin UI.
  // The landing page keeps polling metrics, so networkidle never settles.
  await page.waitForURL(/\/Marti\//, { timeout: 90_000 });
  await page.waitForLoadState("load");
  await page.waitForTimeout(1_500);
  await page.mouse.move(mouse.x, mouse.y);
  caption("Signed in to TAK with a Keycloak account: server monitor");
  mark("zoom", "0.5,0.35,1.3");
  await page.waitForTimeout(4_500);

  await visit(page, "/Marti/inputs/index.html", "Inputs and data feeds");
  await visit(page, "/Marti/security/index.html", "Security and authentication");
}
