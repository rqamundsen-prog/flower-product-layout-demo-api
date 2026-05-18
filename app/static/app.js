const form = document.querySelector("#layout-form");
const result = document.querySelector("#result");
const statusBadge = document.querySelector("#status");
const submit = document.querySelector(".submit");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  statusBadge.textContent = "处理中";
  statusBadge.className = "status";
  submit.disabled = true;

  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || `HTTP ${response.status}`);
    }
    result.textContent = JSON.stringify(body, null, 2);
    statusBadge.textContent = body.validation?.status || "ok";
    statusBadge.className = "status ok";
  } catch (error) {
    result.textContent = JSON.stringify({ error: String(error.message || error) }, null, 2);
    statusBadge.textContent = "错误";
    statusBadge.className = "status error";
  } finally {
    submit.disabled = false;
  }
});
