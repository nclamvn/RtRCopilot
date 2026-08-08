import {expect, test} from "@playwright/test";
import {
  groundedAnswer,
  mockAsk,
  mockAuth,
  mockDocuments,
  mockFiles,
  mockKnowledgeOps,
} from "./support/mocks";

async function chromaticPaint(page: import("@playwright/test").Page) {
  return page.locator("body").evaluate(body => {
    const properties = [
      "color", "background-color", "border-top-color", "border-right-color",
      "border-bottom-color", "border-left-color", "outline-color",
      "text-decoration-color", "fill", "stroke",
    ];
    const findings: Array<{element: string; property: string; value: string}> = [];
    for (const element of body.querySelectorAll("*")) {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      if (!rect.width || !rect.height || style.display === "none"
        || style.visibility === "hidden") continue;
      for (const property of properties) {
        const value = style.getPropertyValue(property);
        const channels = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (!channels) continue;
        const rgb = channels.slice(1, 4).map(Number);
        if (Math.max(...rgb) - Math.min(...rgb) > 2) {
          findings.push({
            element: `${element.tagName.toLowerCase()}.${element.getAttribute("class") ?? ""}`,
            property,
            value,
          });
        }
      }
    }
    return findings;
  });
}

test("1280 Ask keeps a readable stream and opens proof on demand", async ({page}) => {
  await page.setViewportSize({width: 1280, height: 720});
  await mockAsk(page, {...groundedAnswer, answer: [
    "HERA là nền tảng UAV đa nhiệm chủ lực của Real-time Robotics cho ISR và nhiệm vụ dân sự. [C1]",
    "Cấu hình signature 1–4–14 kết hợp một người triển khai, bốn khoang payload và tải trọng 14 kg. [C1]",
    "Họ sản phẩm dùng chung nền tảng gồm HeraHub, HeraSight, pin, sạc và các module nhiệm vụ. [C1]",
  ].join(" ")});
  await page.goto("/ask");
  const surface = page.locator(".ask-surface");
  const composer = page.locator(".ask-form");
  await expect(surface).toBeVisible();
  const before = await surface.boundingBox();
  expect(before?.width ?? 0).toBeGreaterThanOrEqual(620);
  expect((await composer.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(700);
  await expect(composer).toHaveCSS("position", "relative");
  await expect(composer).toHaveCSS("box-shadow", "none");
  const contextControls = await page.locator([
    ".ask-chip:visible",
    ".ask-advanced > summary:visible",
  ].join(",")).evaluateAll(elements => elements.map(element => ({
    height: element.getBoundingClientRect().height,
    radius: Number.parseFloat(getComputedStyle(element).borderRadius),
  })));
  expect(contextControls.every(control => control.height >= 30)).toBe(true);
  expect(contextControls.every(control => control.radius >= 15)).toBe(true);
  const sendGeometry = await page.locator(".ask-send").evaluate(element => ({
    width: element.getBoundingClientRect().width,
    height: element.getBoundingClientRect().height,
    radius: getComputedStyle(element).borderRadius,
  }));
  expect(sendGeometry).toEqual({width: 36, height: 36, radius: "50%"});
  await page.screenshot({path: "test-results/tip0245-ask-composer-refined.png", fullPage: true});
  const rail = page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"});
  await expect(rail).not.toHaveClass(/open/);

  await page.getByLabel("Câu hỏi").fill("Chính sách bảo hành robot?");
  await page.getByRole("button", {name: "Gửi câu hỏi"}).click();
  const claims = page.locator(".ask-answer .answer-claim");
  await expect(claims).toHaveCount(3);
  const answerMeasure = await page.locator(".ask-answer .answer-content").boundingBox();
  expect(answerMeasure?.width ?? 999).toBeLessThanOrEqual(760);
  await expect(claims.nth(1)).toHaveCSS("border-top-width", "1px");
  await page.screenshot({path: "test-results/tip0245-answer-brief-refined.png", fullPage: true});
  await page.getByRole("button", {name: /Trích dẫn — mở bằng chứng.*C1/}).first().click();
  await expect(rail).toHaveClass(/open/);
  await expect.poll(async () => (await rail.boundingBox())?.x ?? 1280)
    .toBeLessThan(1280);
  expect((await rail.boundingBox())?.width ?? 0).toBeGreaterThanOrEqual(360);
  await expect(page.locator("#rail-entry-C1")).toBeFocused();
});

test("desktop search shares the workspace content spine", async ({page}) => {
  await page.setViewportSize({width: 1280, height: 720});
  await mockAsk(page);
  await page.goto("/ask");

  const search = await page.locator(".pc-search").boundingBox();
  const pageHeader = await page.locator(".page-head").boundingBox();
  expect(Math.abs((search?.x ?? 0) - (pageHeader?.x ?? 0))).toBeLessThanOrEqual(1);
});

test("all primary workspaces use one compact inline title grammar", async ({page}) => {
  await page.setViewportSize({width: 1280, height: 720});
  await mockAsk(page);
  await mockFiles(page);
  await mockDocuments(page);

  for (const item of [
    {path: "/ask", workspace: ".ask-workspace"},
    {path: "/files", workspace: ".files-workspace"},
    {path: "/documents", workspace: ".document-workspace-embed"},
  ]) {
    await page.goto(item.path);
    await expect(page.locator(item.workspace)).toBeVisible();
    const geometry = await page.locator(".page-head").evaluate(header => {
      const title = header.querySelector("h1")!.getBoundingClientRect();
      const eyebrow = header.querySelector(".eyebrow")!.getBoundingClientRect();
      const own = header.getBoundingClientRect();
      return {
        height: own.height,
        titleCenter: title.y + title.height / 2,
        eyebrowCenter: eyebrow.y + eyebrow.height / 2,
        titleSize: Number.parseFloat(getComputedStyle(header.querySelector("h1")!).fontSize),
      };
    });
    expect(geometry.height).toBe(50);
    expect(Math.abs(geometry.titleCenter - geometry.eyebrowCenter)).toBeLessThanOrEqual(5);
    expect(geometry.titleSize).toBe(17);
  }
});

test("wide primary workspaces reach the viewport edge without decorative frames", async ({page}) => {
  await page.setViewportSize({width: 1920, height: 1080});
  await mockAsk(page);
  await mockFiles(page);
  await mockDocuments(page);

  for (const item of [
    {path: "/files", selector: ".files-layout", area: "files"},
    {path: "/documents", selector: ".doc-layout", area: "documents"},
  ]) {
    await page.goto(item.path);
    await expect(page.locator(item.selector)).toBeVisible();
    const geometry = await page.locator(item.selector).evaluate(element => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      const main = document.querySelector(".pc-main")!;
      return {
        bottom: rect.bottom,
        borderWidth: style.borderTopWidth,
        viewportBottom: window.innerHeight,
        activeArea: main.getAttribute("data-active-area"),
      };
    });
    expect(Math.abs(geometry.viewportBottom - geometry.bottom)).toBeLessThanOrEqual(1);
    expect(geometry.borderWidth).toBe("0px");
    expect(geometry.activeArea).toBe(item.area);
  }

  await page.goto("/ask");
  await expect(page.locator(".ask-form")).toBeVisible();
  const askGeometry = await page.locator(".ask-workspace").evaluate(workspace => {
    const form = workspace.querySelector(".ask-form")!.getBoundingClientRect();
    const rail = workspace.querySelector(".processing-inspector")!.getBoundingClientRect();
    const main = document.querySelector(".pc-main")!;
    return {
      composerGap: window.innerHeight - form.bottom,
      railGap: window.innerHeight - rail.bottom,
      workspaceGap: window.innerHeight - workspace.getBoundingClientRect().bottom,
      activeArea: main.getAttribute("data-active-area"),
    };
  });
  expect(askGeometry.composerGap).toBeLessThanOrEqual(16);
  expect(Math.abs(askGeometry.railGap)).toBeLessThanOrEqual(1);
  expect(Math.abs(askGeometry.workspaceGap)).toBeLessThanOrEqual(1);
  expect(askGeometry.activeArea).toBe("ask");
});

test("file type filters read as one segmented control instead of eight boxes", async ({page}) => {
  await page.setViewportSize({width: 1440, height: 900});
  await mockAuth(page);
  await mockFiles(page);
  await page.goto("/files");
  await expect(page.locator(".files-layout")).toBeVisible();
  await expect(page.locator(".type-filters button")).toHaveCount(8);
  const styles = await page.locator(".type-filters").evaluate(group => ({
    groupRadius: getComputedStyle(group).borderRadius,
    buttonBorders: Array.from(group.querySelectorAll("button"))
      .map(button => getComputedStyle(button).borderTopWidth),
  }));
  expect(styles.groupRadius).toBe("10px");
  expect(styles.buttonBorders.every(width => width === "0px")).toBe(true);
});

test("Ask composer is transparent, bottom-anchored and keeps context below typing", async ({page}) => {
  await page.setViewportSize({width: 1280, height: 720});
  await mockAsk(page);
  await page.goto("/ask");

  const geometry = await page.locator(".ask-surface").evaluate(surface => {
    const read = (selector: string) => {
      const element = surface.querySelector(selector)!;
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {x: rect.x, y: rect.y, width: rect.width, height: rect.height,
        right: rect.right, bottom: rect.bottom, background: style.backgroundColor};
    };
    const surfaceRect = surface.getBoundingClientRect();
    return {
      surfaceBottom: surfaceRect.bottom,
      form: read(".ask-form"),
      question: read(".ask-question"),
      textarea: read("textarea"),
      context: read(".ask-composer-context"),
      actions: read(".action-row"),
      appBackground: getComputedStyle(document.querySelector(".pc-shell")!).backgroundColor,
    };
  });

  expect(geometry.surfaceBottom - geometry.form.bottom).toBeLessThanOrEqual(20);
  expect(geometry.context.y).toBeGreaterThanOrEqual(geometry.question.bottom);
  expect(Math.abs(geometry.context.bottom - geometry.actions.bottom)).toBeLessThanOrEqual(4);
  expect(geometry.context.right).toBeLessThanOrEqual(geometry.actions.x);
  expect(geometry.textarea.background).toBe("rgba(0, 0, 0, 0)");
  expect(geometry.form.background).toBe(geometry.appBackground);
});

test("1280 Knowledge Ops has no compressed vertical detail column", async ({page}) => {
  await page.setViewportSize({width: 1280, height: 800});
  await mockKnowledgeOps(page);
  await page.goto("/knowledge-ops?view=gaps");
  await expect(page.locator(".ops-split")).toBeVisible();
  const detail = await page.locator(".ops-detail").boundingBox();
  expect(detail?.width ?? 0).toBeGreaterThanOrEqual(240);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("390 Files removes the phantom grid row and stays inside the viewport", async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await mockAuth(page);
  await mockFiles(page);
  await page.goto("/files");
  const layout = await page.locator(".files-layout").boundingBox();
  const work = await page.locator(".files-layout > .work-surface").boundingBox();
  expect(Math.abs((work?.y ?? 0) - (layout?.y ?? 0))).toBeLessThanOrEqual(1);
  expect(Math.abs((work?.width ?? 0) - (layout?.width ?? 0))).toBeLessThanOrEqual(2);
  await page.getByRole("button", {name: "Danh mục", exact: true}).click();
  const catalog = page.locator(".files-layout > .catalog");
  await expect(catalog).toHaveClass(/open/);
  await expect.poll(async () => (await catalog.boundingBox())?.x ?? -1).toBeCloseTo(0, 0);
  const catalogBox = await catalog.boundingBox();
  expect(catalogBox?.width ?? 0).toBeGreaterThanOrEqual(320);
  const filterGeometry = await page.locator(".type-filters button").evaluateAll(buttons =>
    buttons.map(button => ({
      height: button.getBoundingClientRect().height,
      radius: getComputedStyle(button).borderRadius,
    })),
  );
  expect(filterGeometry.length).toBeGreaterThanOrEqual(8);
  expect(filterGeometry.every(button => button.height >= 44)).toBe(true);
  expect(filterGeometry.every(button => button.radius === "10px")).toBe(true);
  await page.screenshot({path: "test-results/tip0245-file-filters-refined.png", fullPage: true});
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("390 core shell and Ask controls meet the 44px touch contract", async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await mockAsk(page);
  await page.goto("/ask");
  const undersized = await page.locator([
    ".pc-topbar button:visible",
    ".pc-dock a:visible",
    ".ask-form .action-row button:visible",
    ".ask-advanced > summary:visible",
  ].join(",")).evaluateAll(elements => elements.flatMap(element => {
    const rect = element.getBoundingClientRect();
    return rect.width < 44 || rect.height < 44
      ? [{label: element.getAttribute("aria-label") || element.textContent, width: rect.width, height: rect.height}]
      : [];
  }));
  expect(undersized).toEqual([]);
  await page.screenshot({path: "test-results/tip0245-ask-mobile-refined.png", fullPage: true});
});

test("Ask is strictly achromatic in dark and light themes", async ({page, context}) => {
  await context.addCookies([{
    name: "rtr_theme",
    value: "dark",
    url: "http://127.0.0.1:3000",
  }]);
  await mockAsk(page);
  await page.goto("/ask");
  await page.getByLabel("Câu hỏi").fill("Chính sách bảo hành robot?");
  const action = page.getByRole("button", {name: "Gửi câu hỏi"});
  await expect(action).toHaveCSS("background-color", "rgb(242, 242, 242)");
  await expect(action).toHaveCSS("color", "rgb(11, 11, 11)");
  expect(await chromaticPaint(page)).toEqual([]);

  await page.getByRole("button", {name: "Chuyển sang giao diện sáng"}).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(action).toHaveCSS("background-color", "rgb(23, 23, 23)");
  await expect(action).toHaveCSS("color", "rgb(255, 255, 255)");
  expect(await chromaticPaint(page)).toEqual([]);
});

test("system integrity stays pinned immediately above the account footer", async ({page}) => {
  await page.setViewportSize({width: 1280, height: 720});
  await mockAsk(page);
  await page.goto("/ask");
  const scroll = page.locator(".pc-sidebar-scroll");
  const integrity = page.locator(".pc-sidebar-footer .pc-integrity");
  const profile = page.locator(".pc-sidebar-footer .pc-profile");
  await expect(integrity).toBeVisible();

  const before = await integrity.boundingBox();
  await scroll.evaluate(element => { element.scrollTop = element.scrollHeight; });
  const after = await integrity.boundingBox();
  const account = await profile.boundingBox();
  expect(Math.abs((before?.y ?? 0) - (after?.y ?? 0))).toBeLessThanOrEqual(1);
  expect((after?.y ?? 0) + (after?.height ?? 0)).toBeLessThanOrEqual(account?.y ?? 0);
});

test("search and composer use quiet focus states without surrounding frames", async ({page}) => {
  await mockAsk(page);
  await page.goto("/ask");
  const search = page.getByRole("button", {name: "Hỏi hoặc tìm trong tri thức công ty"});
  const composer = page.locator(".ask-form");
  const question = page.getByLabel("Câu hỏi");
  const formBefore = await composer.evaluate(element => {
    const style = getComputedStyle(element);
    return {border: style.borderColor, shadow: style.boxShadow};
  });

  await search.focus();
  await expect(search).toBeFocused();
  const searchFocus = await search.evaluate(element => {
    const style = getComputedStyle(element);
    return {outline: style.outlineWidth, shadow: style.boxShadow};
  });
  expect(searchFocus.outline).toBe("0px");
  expect(searchFocus.shadow).toBe("none");

  await question.focus();
  const questionFocus = await question.evaluate(element => {
    const style = getComputedStyle(element);
    return {outline: style.outlineWidth, shadow: style.boxShadow};
  });
  const formAfter = await composer.evaluate(element => {
    const style = getComputedStyle(element);
    return {border: style.borderColor, shadow: style.boxShadow};
  });
  expect(questionFocus).toEqual({outline: "0px", shadow: "none"});
  expect(formAfter).toEqual(formBefore);
});
