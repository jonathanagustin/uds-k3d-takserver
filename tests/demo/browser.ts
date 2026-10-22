/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// A real, headed Google Chrome window for demo recordings, plus the helpers
// every walkthrough shares: a visible cursor with click rings, uneven typing,
// caption and zoom marks for demo/assemble.sh, and a check that Chrome shows
// the connection as secure. demo/record-browser.sh starts the X display,
// trusts the CAs in this Chrome's NSS store, and captures the screen.
//
// A new walkthrough (another host, another app) imports `test` and the
// helpers from here and calls demo/record-browser.sh with its own spec.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { type BrowserContext, chromium, expect, type Locator, type Page, test as base } from "@playwright/test";

const [windowWidth, windowHeight] = (process.env.DEMO_WINDOW || "1280,630").split(",").map(Number);
const eventsFile = process.env.DEMO_EVENTS || ".playwright/demo/events.json";

type Event = { kind: string; at: number; value: string };
const events: Event[] = [];
let startedAt = Date.now();
let mouse = { x: 640, y: 360 };

// Marks are seconds from start(). demo/record-browser.sh trims the screen
// capture to the same instant, using the "start" mark's wall-clock time.
export function start() {
  startedAt = Date.now();
  events.push({ kind: "start", at: 0, value: String(startedAt / 1000) });
}

export function mark(kind: string, value: string) {
  events.push({ kind, at: (Date.now() - startedAt) / 1000, value });
}

// Captions are not drawn in the page. demo/assemble.sh draws them in a band
// below the recorded area, so they never cover the UI.
export function caption(text: string) {
  mark("caption", text);
}

function saveEvents() {
  mkdirSync(dirname(eventsFile), { recursive: true });
  writeFileSync(eventsFile, JSON.stringify(events, null, 2));
}

// Chrome's own first-run and password prompts would cover the page.
function preferences() {
  return {
    browser: { has_seen_welcome_page: true, check_default_browser: false },
    credentials_enable_service: false,
    profile: { password_manager_enabled: false, default_content_setting_values: { notifications: 2 } },
    translate: { enabled: false },
  };
}

async function launch(): Promise<BrowserContext> {
  const profile = process.env.DEMO_BROWSER_PROFILE || ".playwright/demo/profile";
  mkdirSync(`${profile}/Default`, { recursive: true });
  writeFileSync(`${profile}/Default/Preferences`, JSON.stringify(preferences()));
  return chromium.launchPersistentContext(profile, {
    channel: process.env.DEMO_BROWSER_CHANNEL || "chrome",
    headless: false,
    // The page fills the window, so the capture is Chrome's real tab strip,
    // address bar, and page.
    viewport: null,
    // Certificate errors stay errors. The CAs are trusted in NSS instead.
    ignoreHTTPSErrors: false,
    // Chrome's sandbox stays on, so Chrome shows no unsupported-flag bar.
    chromiumSandbox: true,
    // Without this flag Chrome does not show its "controlled by automated
    // test software" bar.
    ignoreDefaultArgs: ["--enable-automation"],
    args: [
      "--window-position=0,0",
      // On a display exactly the window's size, Chrome makes the window one
      // pixel short each way and leaves a black edge. One pixel over fills it.
      `--window-size=${windowWidth + 1},${windowHeight + 1}`,
      "--disable-features=Translate,PasswordLeakDetection,AutofillServerCommunication",
      "--hide-crash-restore-bubble",
    ],
    // Chrome on Linux reads trusted CAs from $HOME/.pki/nssdb.
    env: { ...process.env, HOME: process.env.DEMO_BROWSER_HOME || process.env.HOME || "/tmp" },
  });
}

// A visible cursor and a ring on each click. Input comes over CDP, so the X
// pointer never moves and is not captured.
const pointerOverlay = () => {
  const install = () => {
    // Frames get their own document. One cursor, in the top page only.
    if (window.top !== window || document.getElementById("demo-cursor")) {
      return;
    }
    const style = document.createElement("style");
    style.textContent = `
      #demo-cursor { position: fixed; z-index: 2147483647; pointer-events: none;
        width: 30px; height: 30px; margin: -4px 0 0 -4px; left: var(--x, 640px); top: var(--y, 360px); }
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

// The page fixture is a tab in the headed Chrome window. Events are written
// even when the walkthrough fails, so a partial recording can be inspected.
export const test = base.extend<{ page: Page }>({
  page: async ({}, use, testInfo) => {
    const context = await launch();
    await context.addInitScript(pointerOverlay);
    const page = context.pages()[0] ?? (await context.newPage());
    page.on("dialog", (dialog) => dialog.accept());
    // The browser chrome above the page. demo/filters.py looks for blank
    // pages below it.
    const top = await page.evaluate(() => window.outerHeight - window.innerHeight);
    try {
      await use(page);
    } finally {
      if (testInfo.status !== testInfo.expectedStatus) {
        await page.screenshot({ path: testInfo.outputPath("failure.png") }).catch(() => undefined);
      }
      mark("chrome-top", String(top));
      saveEvents();
      await context.close();
    }
  },
});

export { expect };

// Chrome's own verdict on the connection, the one the address bar shows.
const securityStates = new WeakMap<Page, string>();

export async function watchSecurity(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  cdp.on("Security.visibleSecurityStateChanged", (event) => {
    securityStates.set(page, event.visibleSecurityState.securityState);
  });
  await cdp.send("Security.enable");
}

export async function expectSecure(page: Page) {
  await expect
    .poll(() => securityStates.get(page), { message: `address bar security for ${page.url()}`, timeout: 15_000 })
    .toBe("secure");
  mark("secure", new URL(page.url()).host);
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
export async function typeLikeAPerson(page: Page, text: string) {
  for (const key of text) {
    await page.keyboard.type(key);
    await page.waitForTimeout(between(50, 220));
    if (random() < 0.2) {
      await page.waitForTimeout(between(150, 450));
    }
  }
}

// Scrolls with the wheel, a few notches at a time, until the target sits in
// the window. The page area under the address bar is short.
async function scrollToward(page: Page, target: Locator) {
  const box = await target.boundingBox();
  const height = await page.evaluate(() => window.innerHeight);
  if (!box || (box.y >= 0 && box.y + box.height <= height - 40)) {
    return;
  }
  const delta = box.y + box.height / 2 - height * 0.6;
  const notches = 8;
  for (let i = 0; i < notches; i++) {
    await page.mouse.wheel(0, delta / notches);
    await page.waitForTimeout(between(25, 60));
  }
  await page.waitForTimeout(300);
}

export async function glideTo(page: Page, target: Locator) {
  await scrollToward(page, target);
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

export async function clickLikeAPerson(page: Page, target: Locator) {
  await glideTo(page, target);
  await page.mouse.down();
  await page.waitForTimeout(90);
  await page.mouse.up();
}

// Glides to a point on the page and clicks there (for a map canvas).
export async function clickAtLikeAPerson(page: Page, x: number, y: number) {
  await page.mouse.move(mouse.x, mouse.y);
  await page.mouse.move(x, y, { steps: 28 });
  mouse = { x, y };
  await page.waitForTimeout(250);
  await page.mouse.down();
  await page.waitForTimeout(90);
  await page.mouse.up();
}

// Puts the overlay cursor back where it was after a navigation.
export async function showCursor(page: Page) {
  await page.mouse.move(mouse.x, mouse.y);
}

export async function visit(page: Page, url: string, label: string, hold = 2_600) {
  const response = await page.goto(url, { waitUntil: "load", timeout: 60_000 });
  expect(response?.status() ?? 0, `${url} status`).toBeLessThan(400);
  await showCursor(page);
  await expectSecure(page);
  caption(label);
  await page.waitForTimeout(hold);
}
