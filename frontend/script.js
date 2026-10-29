const form = document.querySelector("#analysis-form");
const fileInput = document.querySelector("#csv-file");
const fileLabel = document.querySelector("#file-label");
const button = document.querySelector("#analyze-button");
const message = document.querySelector("#message");
const results = document.querySelector("#results");


function renderMarkdown(markdown) {
  const escapeHTML = (text) =>
    text.replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");

  const lines = escapeHTML(markdown || "").split("\n");
  const output = [];
  let inList = false;

  const inline = (text) => text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");

  for (const line of lines) {
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const item = line.match(/^\s*[-*]\s+(.+)$/);

    if (item) {
      if (!inList) {
        output.push("<ul>");
        inList = true;
      }
      output.push("<li>" + inline(item[1]) + "</li>");
      continue;
    }

    if (inList) {
      output.push("</ul>");
      inList = false;
    }

    if (heading) {
      const level = heading[1].length;
      output.push(`<h${level}>${inline(heading[2])}</h${level}>`);
    } else if (line.trim() === "") {
      continue;
    } else {
      output.push("<p>" + inline(line) + "</p>");
    }
  }

  if (inList) output.push("</ul>");
  return output.join("\n");
}


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
    document.querySelector("#report").innerHTML =
      renderMarkdown(payload.report_markdown || "No report returned.");
    results.hidden = false;
    message.textContent = "Investigation completed. Review the findings before acting.";
  } catch (error) {
    message.textContent = "LIRA error: " + error.message;
  } finally {
    button.disabled = false;
    button.firstElementChild.textContent = "Run investigation";
  }
});
