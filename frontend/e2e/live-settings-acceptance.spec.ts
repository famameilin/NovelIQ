import { expect, test } from "@playwright/test";

test.skip(!process.env.LIVE_SETTINGS_ACCEPTANCE, "requires the local settings API");

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`settings desktop ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    const writes: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) errors.push(`HTTP ${response.status()}`);
    });
    page.on("request", (request) => {
      if (request.url().includes("/api/settings") && request.method() !== "GET") writes.push(request.url());
    });
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "设置", exact: true })).toBeVisible();
    const pool = page.getByRole("region", { name: "模型池", exact: true });
    await expect(pool).toBeVisible();
    await expect(page.getByRole("region", { name: "嵌入模型" })).toBeVisible();
    await expect(page.getByText(/文本服务连接|标注模型池|独立诊断模型|子代理门槛|结构化输出模式|诊断结构化输出|质量监控|人工复核|供应方顺序|连续性/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "添加供应方" })).toHaveCount(0);
    await expect(page.getByLabel("供应方并发上限", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("诊断模型 ID", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "保存设置" })).toBeDisabled();
    await expect(pool.getByRole("button", { name: "保存模型池" })).toBeDisabled();
    for (const password of await page.locator('input[type="password"]').all()) await expect(password).toHaveValue("");

    const diagnosis = pool.getByRole("combobox", { name: "指定诊断模型" });
    const originalDiagnosis = await diagnosis.innerText();
    const originalRows = await pool.getByRole("row").count();
    const modelId = `acceptance-unsaved-model-${viewport.width}`;
    await page.getByRole("button", { name: "新增模型" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "添加", exact: true }).click();
    await expect(dialog.getByRole("alert")).toHaveText("模型 ID 不能为空");
    await expect(dialog.getByLabel("Base URL")).toHaveCount(0);
    await dialog.getByLabel("ID", { exact: true }).fill(modelId);
    await dialog.getByLabel("URL", { exact: true }).fill("https://acceptance.example/v1");
    await dialog.getByRole("button", { name: "添加", exact: true }).click();
    await expect(dialog.getByRole("alert")).toHaveText("Key 不能为空");
    await dialog.getByLabel("Key", { exact: true }).fill("acceptance-draft-key");
    await dialog.getByLabel("权重", { exact: true }).fill("4");
    await dialog.getByLabel("并发", { exact: true }).fill("3");
    await page.screenshot({ path: test.info().outputPath(`settings-model-dialog-${viewport.width}.png`) });
    await dialog.getByRole("button", { name: "添加", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const row = pool.getByRole("row").filter({ hasText: modelId });
    await expect(row).toContainText("https://acceptance.example/v1");
    await expect(row).toContainText("待保存");
    await expect(row).not.toContainText("acceptance-draft-key");
    await expect(pool.getByRole("button", { name: "保存模型池" })).toBeEnabled();
    await expect(page.getByRole("button", { name: "保存设置" })).toBeDisabled();

    await diagnosis.click();
    await page.getByRole("option", { name: modelId, exact: true }).click();
    await expect(diagnosis).toHaveText(modelId);
    await pool.getByRole("button", { name: `编辑模型：${modelId}` }).click();
    await expect(dialog.getByLabel("权重", { exact: true })).toHaveValue("4");
    await expect(dialog.getByLabel("并发", { exact: true })).toHaveValue("3");
    const renamedId = `${modelId}-renamed`;
    await dialog.getByLabel("ID", { exact: true }).fill(renamedId);
    await dialog.getByRole("button", { name: "应用修改", exact: true }).click();
    await expect(diagnosis).toHaveText(renamedId);
    await page.screenshot({ path: test.info().outputPath(`settings-models-${viewport.width}.png`) });

    await pool.getByRole("button", { name: "放弃模型池修改" }).click();
    await expect(pool.getByRole("button", { name: "保存模型池" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "保存设置" })).toBeDisabled();
    await expect(pool.getByRole("button", { name: `编辑模型：${renamedId}` })).toHaveCount(0);
    await expect(pool.getByRole("row")).toHaveCount(originalRows);
    await expect(diagnosis).toHaveText(originalDiagnosis);
    const horizontalOverflow = await page.evaluate(() =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
    expect(horizontalOverflow).toBe(false);
    expect(errors).toEqual([]);
    expect(writes).toEqual([]);
    await page.getByRole("heading", { name: "设置", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath(`settings-desktop-${viewport.width}.png`) });
  });
}
