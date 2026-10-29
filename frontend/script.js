const form = document.querySelector("#analysis-form");
const fileInput = document.querySelector("#csv-file");
const fileLabel = document.querySelector("#file-label");
const button = document.querySelector("#analyze-button");
const message = document.querySelector("#message");
const results = document.querySelector("#results");

fileInput.addEventListener("change", () => {
  fileLabel.textContent = fileInput.files[0]?.name || "Choose a CSV file";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  const rowIndex = Number(document.querySelector("#row-index").value);

  if (!file) {
    message.textContent = "Please select a CSV file.";
    return;
  }
  if (!file.name.toLowerCase().endsWith(".csv")) {
    message.textContent = "Please upload a CSV file.";
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    message.textContent = "The file exceeds the 10 MB limit.";
    return;
  }
  if (!Number.isInteger(rowIndex) || rowIndex < 0) {
    message.textContent = "Enter a valid row index (0 or greater).";
    return;
  }

  const data = new FormData();
  data.append("file", file);
  button.disabled = true;
  button.firstElementChild.textContent = "Investigating…";
  message.textContent = "Sending file to LIRA. The LLM investigation may use API credit.";
  results.hidden = true;

  try {
    const response = await fetch("/investigate?row_index=" + rowIndex, {
      method: "POST",
      body: data
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || `Request failed (${response.status})`);
    }

    document.querySelector("#result-summary").textContent =
      `Row ${payload.row_index} · Investigation ${payload.investigation_id}`;
    document.querySelector("#detection").textContent =
      JSON.stringify(payload.detection, null, 2);
    document.querySelector("#report").textContent =
      payload.report_markdown || "No Markdown report returned.";
    results.hidden = false;
    message.textContent = "Investigation completed. Review the findings before acting.";
  } catch (error) {
    message.textContent = "LIRA error: " + error.message;
  } finally {
    button.disabled = false;
    button.firstElementChild.textContent = "Run investigation";
  }
});
