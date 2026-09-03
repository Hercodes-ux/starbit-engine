// Core Starbit Engine frontend logic: dataset upload, asking questions,
// rendering the LangGraph agent trace as RPG dialogue boxes, driving the
// animated agent data-flow diagram, and drawing Pixelcraft's Plotly chart.

(function () {
  const API = window.STARBIT_API_BASE;
  const MAX_QUESTIONS = 5;
  const FLOW_NODES = ["dataset", "databit", "pixelcraft", "spirit"];

  const AGENT_LABELS = {
    databit: "DATABIT",
    pixelcraft: "PIXELCRAFT",
    spirit: "SPIRIT",
  };

  // ── Animated neuron/synapse data-flow diagram ──────────
  // Lights up the relevant node and bursts the connector's signal
  // particles brighter/faster each time an agent produces a trace step,
  // so the diagram visually mirrors the dialogue log underneath it in
  // real time. Spirit additionally drives a live eval-harness verdict
  // badge -- "checking" while it works, then "pass"/"revise" once the
  // graph's critic node actually renders a verdict.
  function pulseFlowNode(nodeName) {
    const node = document.querySelector(`.flow-node[data-node="${nodeName}"]`);
    if (!node) return;

    node.classList.remove("pulse");
    void node.getBoundingClientRect(); // force reflow so the animation restarts
    node.classList.add("pulse");

    const idx = FLOW_NODES.indexOf(nodeName);
    if (idx > 0) {
      const line = document.getElementById(`synapse-${idx}`);
      if (line) {
        line.classList.add("active");
        setTimeout(() => line.classList.remove("active"), 550);
      }
      document.querySelectorAll(`.synapse-particle[data-connector="${idx}"]`).forEach((p) => {
        p.classList.remove("burst");
        void p.getBoundingClientRect();
        p.classList.add("burst");
        setTimeout(() => p.classList.remove("burst"), 600);
      });
    }

    if (nodeName === "spirit") setEvalBadge("checking");
  }

  function resetFlowDiagram() {
    document.querySelectorAll(".flow-node").forEach((n) => n.classList.remove("pulse"));
    document.querySelectorAll(".synapse-line").forEach((l) => l.classList.remove("active"));
    document.querySelectorAll(".synapse-particle").forEach((p) => p.classList.remove("burst"));
    setEvalBadge("idle");
  }

  function setEvalBadge(state) {
    const group = document.getElementById("eval-badge-group");
    const text = document.getElementById("eval-verdict");
    group.classList.remove("checking", "pass", "revise");
    if (state === "checking") {
      group.classList.add("checking");
      text.textContent = "EVALUATING...";
    } else if (state === "pass") {
      group.classList.add("pass");
      text.textContent = "✓ APPROVED";
    } else if (state === "revise") {
      group.classList.add("revise");
      text.textContent = "↻ REVISED";
    } else {
      text.textContent = "STANDING BY";
    }
  }

  // ── Upload screen ──────────────────────────────────────
  const fileInput = document.getElementById("file-input");
  const dropzone = document.getElementById("dropzone");
  const dropzoneText = document.getElementById("dropzone-text");
  const uploadBtn = document.getElementById("btn-upload");
  const uploadStatus = document.getElementById("upload-status");

  let selectedFile = null;

  fileInput.addEventListener("change", () => {
    selectedFile = fileInput.files[0] || null;
    dropzoneText.textContent = selectedFile ? selectedFile.name : ".csv · .db / .sqlite · .duckdb";
    uploadBtn.disabled = !selectedFile;
  });

  ["dragover", "dragenter"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) {
      selectedFile = file;
      fileInput.files = e.dataTransfer.files;
      dropzoneText.textContent = file.name;
      uploadBtn.disabled = false;
    }
  });

  uploadBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    uploadBtn.disabled = true;
    uploadStatus.textContent = "Scanning the dungeon...";
    uploadStatus.classList.remove("error");

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const res = await fetch(`${API}/api/upload`, {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      if (res.status === 401) {
        // Session cookie missing/expired -- send them back to log in cleanly
        // rather than showing a cryptic upload error.
        window.Starbit.showScreen("login");
        return;
      }
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed.");
      }
      const data = await res.json();
      window.Starbit.schemaText = data.schema_text;
      window.Starbit.tableCount = data.tables.length;
      window.Starbit.datasetName = data.dataset_name;
      window.Starbit.questionsRemaining = data.questions_remaining;
      window.Starbit.showScreen("console");
      enterConsole();
    } catch (err) {
      uploadStatus.textContent = `⚠ ${err.message}`;
      uploadStatus.classList.add("error");
      uploadBtn.disabled = false;
    }
  });

  function resetToUploadScreen() {
    document.getElementById("quest-log").innerHTML = "";
    document.getElementById("chart-panel").hidden = true;
    resetFlowDiagram();
    selectedFile = null;
    uploadBtn.disabled = true;
    dropzoneText.textContent = ".csv · .db / .sqlite · .duckdb";
    uploadStatus.textContent = "";
    uploadStatus.classList.remove("error");
    window.Starbit.showScreen("upload");
  }

  document.getElementById("btn-new-dataset").addEventListener("click", resetToUploadScreen);

  // ── Console screen ─────────────────────────────────────
  function enterConsole() {
    document.getElementById("schema-preview").textContent = window.Starbit.schemaText || "";
    document.getElementById("flow-dataset-sub").textContent =
      window.Starbit.tableCount != null ? `${window.Starbit.tableCount} table(s)` : "no file yet";
    renderHearts(window.Starbit.questionsRemaining ?? MAX_QUESTIONS);
    document.getElementById("quest-log").innerHTML = "";
    document.getElementById("chart-panel").hidden = true;
    resetFlowDiagram();
    pulseFlowNode("dataset");
    document.getElementById("question-input").focus();
  }
  window.Starbit.onEnterConsole = enterConsole;

  function renderHearts(remaining) {
    const hearts = document.getElementById("hp-hearts");
    let html = "";
    for (let i = 0; i < MAX_QUESTIONS; i++) {
      html += i < remaining ? "♥ " : '<span class="spent">♥</span> ';
    }
    hearts.innerHTML = html.trim();

    const askBtn = document.getElementById("btn-ask");
    const input = document.getElementById("question-input");
    if (remaining <= 0) {
      askBtn.disabled = true;
      input.disabled = true;
      input.placeholder = "No questions left — upload a new dataset for 5 more.";
    } else {
      askBtn.disabled = false;
      input.disabled = false;
      input.placeholder = "Ask Starbit Engine about your data...";
    }
  }

  function appendDialogue(step) {
    pulseFlowNode(step.agent);

    const log = document.getElementById("quest-log");
    const box = document.createElement("div");
    box.className = "dialogue";
    box.dataset.agent = step.agent;

    const sql = step.payload && step.payload.sql ? `\n${step.payload.sql}` : "";

    box.innerHTML = `
      <div class="sprite sprite-${step.agent}"></div>
      <div class="dialogue-body">
        <div class="dialogue-name">${AGENT_LABELS[step.agent] || step.agent.toUpperCase()}
          <span class="dialogue-kind ${step.kind}">${step.kind.replace("_", " ")}</span>
        </div>
        <div class="dialogue-msg">${escapeHtml(step.message)}</div>
        ${sql ? `<div class="dialogue-sql">${escapeHtml(sql.trim())}</div>` : ""}
      </div>
    `;
    log.appendChild(box);
    box.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  function appendFinalReport(report, passedReview) {
    const log = document.getElementById("quest-log");
    const box = document.createElement("div");
    box.className = "final-report";
    box.innerHTML = `
      <div class="final-report-title">${passedReview ? "◆ PORTAL OPENED — FINAL REPORT" : "◆ REPORT (unreviewed)"}</div>
      <div class="final-report-body">${escapeHtml(report)}</div>
    `;
    log.appendChild(box);
    box.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  function appendSystemLine(message, isError) {
    const log = document.getElementById("quest-log");
    const line = document.createElement("div");
    line.className = "dialogue-msg";
    line.style.margin = "6px 0 14px 4px";
    line.style.color = isError ? "#FF4FA3" : "#FFD447";
    line.textContent = message;
    log.appendChild(line);
    line.scrollIntoView({ behavior: "smooth", block: "end" });
  }

  function renderChart(figureJson) {
    const panel = document.getElementById("chart-panel");
    if (!figureJson) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    const fig = JSON.parse(figureJson);
    Plotly.newPlot("chart-container", fig.data, fig.layout, { displayModeBar: false, responsive: true });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Ask form ────────────────────────────────────────────
  const askForm = document.getElementById("ask-form");
  const questionInput = document.getElementById("question-input");
  const askBtn = document.getElementById("btn-ask");

  askForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = questionInput.value.trim();
    if (!question) return;

    askBtn.disabled = true;
    questionInput.disabled = true;
    appendSystemLine(`▸ You asked: "${question}"`, false);

    try {
      const res = await fetch(`${API}/api/ask`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (res.status === 401) {
        appendSystemLine("⚠ Your login expired. Taking you back to the title screen...", true);
        setTimeout(() => window.Starbit.showScreen("login"), 1400);
        return;
      }

      if (res.status === 409) {
        // Dataset connection lost (almost always a dev-server restart).
        // Login and question count are intact -- just need the file back.
        const err = await res.json();
        appendSystemLine(`⚠ ${err.detail}`, true);
        setTimeout(resetToUploadScreen, 1800);
        return;
      }

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Something went wrong.");
      }

      const data = await res.json();
      console.log("[Starbit] /api/ask response:", data);
      console.log(`[Starbit] steps received: ${data.steps ? data.steps.length : "undefined"}`);

      if (!data.steps || data.steps.length === 0) {
        // Should never happen -- the backend always emits at least a
        // handful of trace steps for a successful run. If it does happen,
        // make it visible instead of silently showing nothing.
        appendSystemLine(
          "⚠ No agent trace steps came back with this response (check the browser Console for the raw payload).",
          true
        );
      }

      for (const step of data.steps || []) {
        try {
          appendDialogue(step);
        } catch (stepErr) {
          console.error("[Starbit] Failed to render a dialogue step:", step, stepErr);
          appendSystemLine(`⚠ Failed to render one trace step (${stepErr.message}) — see Console for details.`, true);
        }
        await sleep(120); // small stagger so the trace reads like a sequence, not a dump
      }

      renderChart(data.figure_json);
      appendFinalReport(data.final_report, data.passed_review);
      setEvalBadge(data.passed_review ? "pass" : "revise");
      renderHearts(data.questions_remaining);
      questionInput.value = "";
    } catch (err) {
      appendSystemLine(`⚠ ${err.message}`, true);
    } finally {
      questionInput.disabled = window.Starbit.questionsRemaining === 0;
      askBtn.disabled = false;
      questionInput.focus();
    }
  });

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
})();