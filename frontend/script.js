
const form = document.querySelector("#analysis-form");
const fileInput = document.querySelector("#csv-file");
const fileLabel = document.querySelector("#file-label");
const button = document.querySelector("#analyze-button");
const message = document.querySelector("#message");
const results = document.querySelector("#results");
const reportPanel = document.querySelector("#report-panel");
const mainContainer = document.querySelector(".container");

// Escape HTML before inserting dynamic values into HTML.
function escapeHTML(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdown(markdown) {
  const cleaned = (markdown || "")
    .replace(/```json[\s\S]*?```/gi, "")
    .replace(/```[\s\S]*?```/g, "")
    .trim();

  const lines = escapeHTML(cleaned).split("\n");
  const output = [];
  let inList = false;

  const inline = (text) => text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");

  for (const line of lines) {
    if (
      line.trim().startsWith('"tool"') ||
      line.trim().startsWith('"valid"') ||
      line.trim().startsWith('"rows_checked"')
    ) {
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const item = line.match(/^\s*[-*]\s+(.+)$/);

    if (item) {
      if (!inList) {
        output.push("<ul>");
        inList = true;
      }
      output.push(`<li>${inline(item[1])}</li>`);
      continue;
    }

    if (inList) {
      output.push("</ul>");
      inList = false;
    }

    if (heading) {
      const level = heading[1].length;
      output.push(
        `<h${level}>${inline(heading[2])}</h${level}>`
      );
    } else if (line.trim()) {
      output.push(`<p>${inline(line)}</p>`);
    }
  }

  if (inList) output.push("</ul>");

  return output.join("\n");
}

function setButtonLoading(isLoading) {
  button.disabled = isLoading;

  const buttonText = button.querySelector("span");
  if (buttonText) {
    buttonText.textContent = isLoading
      ? "Investigating…"
      : "Run investigation";
  }
}

fileInput.addEventListener("change", () => {
  fileLabel.textContent =
    fileInput.files[0]?.name || "Choose a CSV file";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const file = fileInput.files[0];
  const rowIndex = Number(
    document.querySelector("#row-index").value
  );

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
    message.textContent =
      "Enter a valid row index (0 or greater).";
    return;
  }

  const data = new FormData();
  data.append("file", file);

  setButtonLoading(true);
  message.textContent =
    "Sending file to LIRA. The LLM investigation may use API credit.";

  results.hidden = true;
  if (reportPanel) reportPanel.hidden = true;
  mainContainer.classList.remove("has-results");

  try {
    const response = await fetch(
      `/investigate?row_index=${rowIndex}`,
      {
        method: "POST",
        body: data
      }
    );

    const payload = await response.json();

    if (!response.ok) {
      throw new Error(
        payload.detail || `Request failed (${response.status})`
      );
    }

    const detection = payload.detection;

    if (!detection || typeof detection !== "object") {
      throw new Error("The API returned invalid detection data.");
    }

    const investigation = payload.investigation || {};
    const probabilities = detection.probabilities || {};

    document.querySelector("#result-summary").textContent =
      `Row ${payload.row_index} · Investigation ${
        String(payload.investigation_id || "").slice(0, 8)
      }…`;

    document.querySelector("#prediction").textContent =
      detection.prediction || "UNKNOWN";

    const statusElement =
      document.querySelector("#detection-status");

    const status = String(detection.status || "UNKNOWN").toUpperCase();
    const allowedStatuses = ["ATTACK", "BENIGN", "UNKNOWN"];

    statusElement.textContent = status;
    statusElement.className =
      "detection-status " +
      (allowedStatuses.includes(status)
        ? status.toLowerCase()
        : "unknown");

    const rawConfidence = Number(detection.confidence);
    const confidence = Number.isFinite(rawConfidence)
      ? Math.max(0, Math.min(1, rawConfidence))
      : 0;

    const confidencePercent = confidence * 100;

    document.querySelector("#confidence").textContent =
      confidencePercent.toFixed(1) + "%";

    document.querySelector("#confidence-bar").style.width =
      confidencePercent + "%";

    document.querySelector("#probabilities").innerHTML =
      Object.entries(probabilities)
        .map(([label, value]) => {
          const numericValue = Number(value);
          const safeValue = Number.isFinite(numericValue)
            ? Math.max(0, Math.min(1, numericValue))
            : 0;

          const percent = safeValue * 100;

          return `
            <div class="probability-row">
              <div class="metric-heading">
                <span>${escapeHTML(label)}</span>
                <strong>${percent.toFixed(1)}%</strong>
              </div>
              <div class="progress-track">
                <div class="progress-fill"
                     style="width:${percent}%"></div>
              </div>
            </div>
          `;
        })
        .join("");

    document.querySelector("#detection").textContent =
      JSON.stringify(detection, null, 2);

    document.querySelector("#report").innerHTML =
      renderMarkdown(
        payload.report_markdown || "No report returned."
      );

    results.hidden = false;
    if (reportPanel) reportPanel.hidden = false;
    mainContainer.classList.add("has-results");

    const investigationStatus = String(
      investigation.status || "UNKNOWN"
    ).toUpperCase();

    message.textContent =
      investigationStatus === "FAILED"
        ? "Investigation failed. Review the available findings and error details."
        : "Investigation finished. Review the findings before acting.";

    // Scroll only on mobile-sized screens.
    if (window.innerWidth < 1100) {
      results.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    }

  } catch (error) {
    message.textContent = "LIRA error: " + error.message;
  } finally {
    setButtonLoading(false);
  }
});
                      
