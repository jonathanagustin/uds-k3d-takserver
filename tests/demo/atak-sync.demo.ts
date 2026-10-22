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

async function scene(page: Page, name: string, body: () => Promise<void>) {
  try {
    await body();
    return true;
  } catch (error) {
    console.log(`scene ${name} skipped: ${String(error).split("\n")[0]}`);
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
  test.setTimeout(420_000);
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
  await watchSecurity(map);
  await map.goto(mapUrl);
  await expect(map.locator("canvas.maplibregl-canvas")).toBeVisible({ timeout: 120_000 });
  await map
    .getByRole("button", { name: "Skip for now" })
    .waitFor({ state: "visible", timeout: 15_000 })
    .catch(() => undefined);
  for (let i = 0; i < 10; i++) {
    let open = false;
    for (const name of ["Not now", "Skip for now"]) {
      const skip = map.getByRole("button", { name });
      if (await skip.isVisible().catch(() => false)) {
        open = true;
        await clickLikeAPerson(map, skip).catch(() => undefined);
      }
    }
    if (!open) break;
    await map.waitForTimeout(800);
  }
  await map.evaluate((loc) => {
    window.location.hash = `#15/${loc}`;
  }, testLocation);
  await map.waitForTimeout(3_000);
  await expectSecure(map);
  caption("CloudTAK on the same TAK Server, at the device's TEST LOCATION");
  await map.waitForTimeout(3_000);

  // CloudTAK -> ATAK: draw a point, name it TEST MARKER, share it to the device.
  const marker = await scene(map, "marker", async () => {
    await clickLikeAPerson(map, map.getByTitle("Geometry Editing", { exact: true }));
    await clickLikeAPerson(map, map.getByText("Draw Point", { exact: true }));
    const at = await canvasPoint(map, 220, -90);
    await clickAtLikeAPerson(map, at.x, at.y);
    await expect(map).toHaveURL(/\/cot\//, { timeout: 15_000 });
    await clickLikeAPerson(map, map.getByTitle("Edit", { exact: true }).first());
    await map.keyboard.press("Control+A");
    await typeLikeAPerson(map, "TEST MARKER");
    await map.keyboard.press("Enter");
    await expect(map.getByText("TEST MARKER", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
    caption("A TEST MARKER drawn in CloudTAK");
    await map.waitForTimeout(2_000);
    await clickLikeAPerson(map, map.getByTitle("Share", { exact: true }).first());
    const modal = map.locator(".modal").filter({ hasText: "Share Features" });
    await expect(modal).toBeVisible({ timeout: 10_000 });
    await clickLikeAPerson(map, modal.getByText(deviceCallsign, { exact: true }).first());
    await clickLikeAPerson(map, modal.getByTitle("Share to Selected"));
    caption("Shared to the ATAK device through TAK");
    await map.waitForTimeout(3_000);
  });

  // CloudTAK -> ATAK: a TEST chat message to the device.
  const chat = await scene(map, "chat", async () => {
    await map.evaluate((loc) => {
      window.location.hash = `#15/${loc}`;
    }, testLocation);
    await map.waitForTimeout(1_500);
    const centre = await canvasPoint(map);
    await clickAtLikeAPerson(map, centre.x, centre.y);
    await expect(map.getByText(deviceCallsign, { exact: true }).first()).toBeVisible({ timeout: 10_000 });
    await clickLikeAPerson(map, map.getByTitle("More Actions", { exact: true }).first());
    await clickLikeAPerson(map, map.getByText("Chat", { exact: true }).first());
    const input = map.getByPlaceholder("Send Message...");
    await expect(input).toBeVisible({ timeout: 10_000 });
    await clickLikeAPerson(map, input);
    await typeLikeAPerson(map, "TEST MESSAGE from CloudTAK");
    await map.keyboard.press("Enter");
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

  // TAK's own view: the device's certificate-authenticated connection.
  const tak = await page.context().newPage();
  await watchSecurity(tak);
  await scene(tak, "clients", async () => {
    await tak.goto(new URL("/Marti/clients/index.html", takUrl).toString(), { timeout: 60_000 });
    await expect(tak.getByText(deviceCallsign).first()).toBeVisible({ timeout: 60_000 });
    await showCursor(tak);
    await expectSecure(tak);
    caption("TAK's client list: the device, authenticated by its own client certificate");
    mark("zoom", "0.5,0.4,1.4");
    await tak.waitForTimeout(6_000);
  });
});
