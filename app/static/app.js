const form = document.querySelector("#layout-form");
const result = document.querySelector("#result");
const statusBadge = document.querySelector("#status");
const submit = document.querySelector(".submit");
const submitLabel = document.querySelector(".button-label");
const fileInput = document.querySelector("#files");
const fileSummary = document.querySelector("#file-summary");
const runMeta = document.querySelector("#run-meta");
const pipelineFill = document.querySelector("#pipeline-fill");
const steps = Array.from(document.querySelectorAll(".step"));

const phaseProgress = {
  ready: 8,
  queued: 34,
  processing: 68,
  completed: 100,
  failed: 100,
};

let startedAt = 0;
let elapsedTimer = 0;

fileInput?.addEventListener("change", () => {
  const files = Array.from(fileInput.files || []);
  if (!files.length) {
    fileSummary.textContent = "尚未选择文件";
    return;
  }
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  fileSummary.textContent = `${files.length} 个文件 / ${formatBytes(totalBytes)}`;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  beginGenerating();

  try {
    const createResponse = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
    });
    const created = await createResponse.json();
    if (!createResponse.ok) {
      throw new Error(created.detail || `HTTP ${createResponse.status}`);
    }
    setPhase("queued", "生成中");
    setRunMeta(created.jobId, "queued");
    result.textContent = JSON.stringify(
      {
        jobId: created.jobId,
        status: created.status,
        message: "任务已创建，等待 AI 分析。",
      },
      null,
      2,
    );
    await pollJob(created.statusUrl);
  } catch (error) {
    result.textContent = JSON.stringify({ error: String(error.message || error) }, null, 2);
    setPhase("failed", "错误");
    setRunMeta(currentJobId(), "failed");
  } finally {
    endGenerating();
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
      setPhase("completed", body.result?.documentType || "完成");
      setRunMeta(body.jobId, "completed");
      return;
    }

    if (body.status === "failed") {
      setRunMeta(body.jobId, "failed");
      throw new Error(body.error || "AI 任务失败");
    }

    setPhase(body.status === "queued" ? "queued" : "processing", "生成中");
    setRunMeta(body.jobId, body.status);
    result.textContent = JSON.stringify(
      {
        jobId: body.jobId,
        status: body.status,
        elapsed: formatElapsed(Date.now() - startedAt),
        message: "AI 正在后台分析资料，结果会自动刷新。",
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

function beginGenerating() {
  startedAt = Date.now();
  submit.disabled = true;
  submit.classList.add("is-loading");
  submitLabel.textContent = "生成中";
  result.textContent = "任务提交中...";
  setPhase("queued", "生成中");
  setRunMeta("-", "queued");
  window.clearInterval(elapsedTimer);
  elapsedTimer = window.setInterval(() => {
    setRunMeta(currentJobId(), statusBadge.textContent || "processing");
  }, 1000);
}

function endGenerating() {
  submit.disabled = false;
  submit.classList.remove("is-loading");
  submitLabel.textContent = "生成 JSON";
  window.clearInterval(elapsedTimer);
}

function setPhase(phase, label) {
  statusBadge.textContent = label;
  statusBadge.className = `status ${phase}`;
  pipelineFill.style.width = `${phaseProgress[phase] || 0}%`;
  steps.forEach((step) => {
    const stepPhase = step.dataset.phase;
    step.classList.toggle("active", stepPhase === phase);
    step.classList.toggle("done", (phaseProgress[stepPhase] || 0) < (phaseProgress[phase] || 0));
  });
}

function setRunMeta(jobId, state) {
  const elapsed = startedAt ? formatElapsed(Date.now() - startedAt) : "00:00";
  runMeta.innerHTML = `<span>job: ${escapeHtml(jobId || "-")}</span><span>state: ${escapeHtml(state || "-")}</span><span>elapsed: ${elapsed}</span>`;
}

function currentJobId() {
  const match = result.textContent.match(/[a-f0-9]{32}/);
  return match ? match[0] : "-";
}

function formatElapsed(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
  const rest = String(seconds % 60).padStart(2, "0");
  return `${minutes}:${rest}`;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return entities[char];
  });
}
