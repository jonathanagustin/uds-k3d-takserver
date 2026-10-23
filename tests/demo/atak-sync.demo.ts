/**
 * Copyright 2026 uds-k3d-takserver authors
 * SPDX-License-Identifier: GPL-3.0-only
 */

// Live sync between CloudTAK and the ATAK test device for the "Operate and
// trust" video: a TEST MARKER drawn in CloudTAK and shared to the device, a
// TEST chat message to the device, both shown arriving on the phone view,
// then TAK's own client list with the device's certificate connection.
// Each scene is skipped (with a screenshot in tests/.playwright/demo) if the
// UI does not do what it should, so the video only shows what worked.
// demo/record-web.sh runs it after atak/ci/e2e.sh has connected the device.
import type { Page } from "@playwright/test";
import {
  caption,
  cloudtakReady,
  clickAtLikeAPerson,
  clickLikeAPerson,
  expect,
  expectSecure,
  mark,
  showCursor,
  start,
  test,
  typeLikeAPerson,
  watchSecurity,
} from "./browser";

const phoneUrl = process.env.ATAK_VIEWER_URL || "https://atak.uds.dev/phone.html";
const mapUrl = process.env.CLOUDTAK_URL || "https://map.uds.dev/";
const takUrl = process.env.TAK_SSO_URL || "https://takserver.uds.dev/";
const username = process.env.KEYCLOAK_USER || "takuser";
const password = process.env.KEYCLOAK_PASSWORD || "";
const deviceCallsign = process.env.ATAK_CALLSIGN || "ATAK-DEVICE (TEST LOCATION)";
const testLocation = process.env.ATAK_TEST_LOCATION || "38.8895/-77.0353";

// Clicking a marker opens CloudTAK's radial menu; its "view" sector opens
// the marker's pane.
async function viewFromRadial(page: Page) {
  const view = page.locator('.menuHolder g[data-id="view"] use').first();
  await expect(view).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(600);
  await clickLikeAPerson(page, view);
}

async function scene(page: Page, name: string, body: () => Promise<void>) {
  try {
    await body();
    return true;
  } catch (error) {
    // Keep the whole message: Playwright puts the locator and the call log
    // after the first line, and that is what says which step failed.
    const detail = String(error).replace(/\u001b\[[0-9;]*m/g, "").split("\n").slice(0, 12).join("\n  ");
    console.log(`scene ${name} skipped: ${detail}`);
    await page.screenshot({ path: test.info().outputPath(`probe-${name}.png`) }).catch(() => undefined);
    return false;
  }
}

async function canvasPoint(map: Page, dx = 0, dy = 0) {
  const box = await map.locator("canvas.maplibregl-canvas").boundingBox();
  if (!box) throw new Error("no map canvas");
  return { x: box.x + box.width / 2 + dx, y: box.y + box.height / 2 + dy };
}

test("CloudTAK and the ATAK test device in sync", async ({ page }) => {
  test.setTimeout(600_000);
  expect(password, "KEYCLOAK_PASSWORD is not set").not.toBe("");
  await watchSecurity(page);

  await page.goto(phoneUrl);
  await expect(page).toHaveURL(/sso\.uds\.dev/, { timeout: 60_000 });
  const userField = page.getByLabel("Username or email");
  await expect(userField).toBeVisible();
  await page.mouse.click(8, 200);
  start();
  await showCursor(page);
  await clickLikeAPerson(page, userField);
  await typeLikeAPerson(page, username);
  await clickLikeAPerson(page, page.getByLabel("Password"));
  await typeLikeAPerson(page, password);
  await clickLikeAPerson(page, page.getByRole("button", { name: "Sign In" }));
  await expect(page).toHaveURL(/phone\.html/, { timeout: 60_000 });
  await expect(page.locator(".screen iframe")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(8_000);
  await expectSecure(page);
  caption("The ATAK test device, connected to TAK over mutual TLS on 8089");
  await page.waitForTimeout(3_000);

  const map = await page.context().newPage();
  map.setDefaultTimeout(30_000);
  await watchSecurity(map);
  await map.goto(mapUrl);
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 120_000 });
  await cloudtakReady(map, "CLOUDTAK-TEST");
  await map.evaluate((loc) => {
    window.location.hash = `#15/${loc}`;
  }, testLocation);
  await map.waitForTimeout(3_000);
  await expectSecure(map);
  caption("ATAK to CloudTAK: the device's TEST LOCATION marker, live from its CoT stream");
  await map.waitForTimeout(3_000);

  // CloudTAK -> ATAK: a named point from Coordinate Entry, a little east of
  // the device, shared to the device.
  const marker = await scene(map, "marker", async () => {
    const [lat, lon] = testLocation.split("/").map(Number);
    await map.evaluate(
      ([la, lo]) => {
        window.location.hash = `#16/${la}/${lo}`;
      },
      [lat, lon + 0.004],
    );
    await map.waitForTimeout(1_500);
    await clickLikeAPerson(map, map.getByTitle("Geometry Editing", { exact: true }));
    await clickLikeAPerson(map, map.getByText("Coordinate Input", { exact: true }));
    // CloudTAK's input label is not tied to the field, so find it by placeholder.
    const name = map.getByPlaceholder("Name", { exact: true });
    await expect(name).toBeVisible({ timeout: 10_000 });
    await clickLikeAPerson(map, name);
    await typeLikeAPerson(map, "TEST MARKER");
    await clickLikeAPerson(map, map.getByRole("button", { name: "Create Point" }));
    await expect(map.getByText("Coordinate Entry", { exact: true })).toBeHidden({ timeout: 10_000 });
    await map.waitForTimeout(2_500);
    caption("A TEST MARKER placed in CloudTAK");
    const centre = await canvasPoint(map);
    await clickAtLikeAPerson(map, centre.x, centre.y);
    await viewFromRadial(map);
    await expect(map).toHaveURL(/\/cot\//, { timeout: 10_000 });
    await expect(map.getByText("TEST MARKER", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
    await clickLikeAPerson(map, map.getByTitle("Share", { exact: true }).first());
    const modal = map.locator(".modal").filter({ hasText: "Share Features" });
    await expect(modal).toBeVisible({ timeout: 10_000 });
    await clickLikeAPerson(map, modal.getByPlaceholder("Filter..."));
    await typeLikeAPerson(map, "ATAK");
    await clickLikeAPerson(map, modal.getByText(deviceCallsign, { exact: true }).first());
    await clickLikeAPerson(map, modal.getByTitle("Share to Selected"));
    caption("Shared to the ATAK device through TAK");
    await map.waitForTimeout(3_000);
  });

  // CloudTAK -> ATAK: a TEST chat message to the device.
  const chat = await scene(map, "chat", async () => {
    for (const title of ["Close Pane", "Close Menu"]) {
      const close = map.getByTitle(title, { exact: true }).first();
      if (await close.isVisible().catch(() => false)) await clickLikeAPerson(map, close);
    }
    await map.evaluate((loc) => {
      window.location.hash = `#16/${loc}`;
    }, testLocation);
    await map.waitForTimeout(2_000);
    const centre = await canvasPoint(map);
    await clickAtLikeAPerson(map, centre.x, centre.y);
    await viewFromRadial(map);
    await expect(map.getByText(deviceCallsign, { exact: true }).first()).toBeVisible({ timeout: 10_000 });
    await clickLikeAPerson(map, map.getByTitle("More Actions", { exact: true }).first());
    await clickLikeAPerson(map, map.getByText("Chat", { exact: true }).first());
    const input = map.getByPlaceholder("Send Message...");
    await expect(input).toBeVisible({ timeout: 10_000 });
    await clickLikeAPerson(map, input);
    await typeLikeAPerson(map, "TEST MESSAGE from CloudTAK");
    await clickLikeAPerson(map, map.getByTitle("Send Message", { exact: true }).first());
    caption("A TEST chat message from CloudTAK to the device");
    await map.waitForTimeout(3_000);
  });

  if (marker || chat) {
    await page.bringToFront();
    await showCursor(page);
    await page.waitForTimeout(2_000);
    caption(
      marker && chat
        ? "On the phone: the TEST MARKER and the chat arrive over the device's stream"
        : marker
          ? "On the phone: the TEST MARKER arrives over the device's stream"
          : "On the phone: the chat arrives over the device's stream",
    );
    mark("zoom", "0.5,0.5,1.4");
    await page.waitForTimeout(7_000);
  }

  // Nothing to show if neither scene worked: fail so the take is left out.
  expect(marker || chat, "no sync scene worked").toBe(true);
});
