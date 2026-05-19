const form = document.querySelector("#layout-form");
const result = document.querySelector("#result");
const statusBadge = document.querySelector("#status");
const submit = document.querySelector(".submit");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusBadge.textContent = "提交中";
  statusBadge.className = "status";
  submit.disabled = true;

  try {
    const createResponse = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
    });
    const created = await createResponse.json();
    if (!createResponse.ok) {
      throw new Error(created.detail || `HTTP ${createResponse.status}`);
    }
    result.textContent = JSON.stringify(created, null, 2);
    await pollJob(created.statusUrl);
  } catch (error) {
    result.textContent = JSON.stringify({ error: String(error.message || error) }, null, 2);
    statusBadge.textContent = "错误";
    statusBadge.className = "status error";
  } finally {
    submit.disabled = false;
  }
});

async function pollJob(statusUrl) {
  if (!statusUrl) {
    throw new Error("任务接口没有返回 statusUrl");
  }

  while (true) {
    const response = await fetch(statusUrl);
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || `HTTP ${response.status}`);
    }

    if (body.status === "completed") {
      result.textContent = JSON.stringify(body.result, null, 2);
      statusBadge.textContent = body.result?.documentType || "完成";
      statusBadge.className = "status ok";
      return;
    }

    if (body.status === "failed") {
      throw new Error(body.error || "AI 任务失败");
    }

    statusBadge.textContent = body.status === "queued" ? "排队中" : "AI处理中";
    result.textContent = JSON.stringify(
      {
        jobId: body.jobId,
        status: body.status,
        message: "AI 正在后台分析资料，网页会自动刷新结果。",
      },
      null,
      2,
    );
    await delay(2000);
  }
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
