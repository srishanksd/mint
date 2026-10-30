let currentExperimentId = null;
let agentRunsCache = [];
let portfolioChartInstance = null;
let isFetchingOverview = false;
let isFetchingLiveState = false;
let lastKnownStatus = null;

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const agentNodeMap = {
  "Opportunity Scout": "scout",
  "Strategy Agent": "strategy",
  "MINT Orchestrator": "orchestrator",
  "Content Creator": "creator",
  "Product Builder": "creator",
  "Quality Checker": "quality",
  "Publishing Agent": "commerce",
  "Measurement Agent": "measurement",
  "Finance Agent": "finance",
  "Portfolio Manager": "portfolio"
};

function formatStatus(status) {
  if (!status) return "Waiting";
  const s = status.toLowerCase();
  if (s === "waiting" || s === "idle") return "Waiting";
  if (s === "running") return "Running";
  if (s === "completed") return "Completed";
  if (s === "interrupted") return "Interrupted";
  if (s === "failed") return "Failed";
  if (s === "needs_review") return "Needs Review";
  if (s === "blocked") return "Blocked";
  return status.replace(/_/g, " ");
}

/* Theme Management & Accessibility */
function initTheme() {
  const saved = localStorage.getItem("mint_theme") || "light";
  applyTheme(saved);
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("mint_theme", theme);
  const btn = document.getElementById("theme-toggle-btn");
  const icon = document.getElementById("theme-icon");
  const text = document.getElementById("theme-text");

  const isDark = theme === "dark";
  if (btn) {
    btn.setAttribute("aria-pressed", isDark ? "true" : "false");
  }
  if (icon && text) {
    if (isDark) {
      icon.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;
      text.innerText = "Light";
    } else {
      icon.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
      text.innerText = "Dark";
    }
  }

  // Update Chart.js palette dynamically
  if (portfolioChartInstance) {
    portfolioChartInstance.data.datasets[0].borderColor = isDark ? "#182234" : "#ffffff";
    portfolioChartInstance.update();
  }
}

function toggleMINTTheme() {
  const curr = document.documentElement.getAttribute("data-theme") || "light";
  const next = curr === "dark" ? "light" : "dark";
  applyTheme(next);
}

/* Initialization & Non-Overlapping Polling */
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  refreshYouTubeStatus();
  fetchOverview();
  loadChatHistory();

  // Lightweight live-state polling every 2.5 seconds
  setInterval(() => {
    if (!isFetchingLiveState) {
      fetchLiveState();
    }
  }, 2500);
});

/* Fetch Full Overview (Financials, Artifacts, Portfolio) */
async function fetchOverview() {
  if (isFetchingOverview) return;
  isFetchingOverview = true;

  try {
    const res = await fetch("/api/overview" + (currentExperimentId ? `?experiment_id=${currentExperimentId}` : ""));
    const data = await res.json();

    if (data.integrations) {
      updateIntegrationBadges(data.integrations);
    }

    if (!data.has_data) {
      isFetchingOverview = false;
      return;
    }

    currentExperimentId = data.experiment.id;
    agentRunsCache = data.agent_runs || [];
    lastKnownStatus = data.experiment.status;

    // Financial Metrics
    const budgetLimit = parseFloat(data.experiment.budget_limit || 0).toFixed(2);
    const budgetUsed = data.experiment.budget_used !== null && data.experiment.budget_used !== undefined
      ? ` (used: $${parseFloat(data.experiment.budget_used).toFixed(2)})`
      : "";
    document.getElementById("val-budget").innerText = `$${budgetLimit}${budgetUsed}`;
    document.getElementById("val-status").innerText = `Status: ${data.experiment.status.toUpperCase()}`;

    if (data.traffic_summary) {
      document.getElementById("val-traffic").innerText = `${data.traffic_summary.views} views`;
      document.getElementById("val-clicks").innerHTML = `${data.traffic_summary.clicks} clicks (${data.traffic_summary.ctr_pct}% CTR)`;
      document.getElementById("val-traffic-source").innerText = data.traffic_summary.views > 0 ? "Verified logs" : "Awaiting traffic";
    }

    if (data.finance) {
      document.getElementById("val-gross").innerText = `$${parseFloat(data.finance.gross_revenue).toFixed(2)}`;
      document.getElementById("val-profit").innerText = `$${parseFloat(data.finance.net_profit).toFixed(2)}`;
      document.getElementById("val-reserve").innerText = `$${parseFloat(data.finance.required_reserve).toFixed(2)}`;
      document.getElementById("val-fees").innerText = `Spend: $${data.finance.actual_spend} | Processing Fees: $${data.finance.fees}`;
    }

    if (data.orders_summary) {
      document.getElementById("val-orders").innerText = `${data.orders_summary.real_orders_count} real ($${parseFloat(data.orders_summary.real_gross || 0).toFixed(2)}) &middot; ${data.orders_summary.test_orders_count} sandbox`;
    }

    // Render Nodes from initial load
    renderNodes(agentRunsCache);

    // Artifact & Digital Product Deliverable
    if (data.artifact) {
      document.getElementById("card-artifact").style.display = "block";
      const complianceBadge = document.getElementById("badge-compliance");
      if (complianceBadge) {
        if (data.artifact.file_status === "missing_asset") {
          complianceBadge.className = "status-pill failed";
          complianceBadge.innerText = "Missing Asset - Media Not Found";
        } else {
          complianceBadge.className = "status-pill connected";
          complianceBadge.innerText = "Verified";
        }
      }
      document.getElementById("art-hook").innerText = data.artifact.hook || data.artifact.title;
      document.getElementById("art-cta").innerText = data.artifact.call_to_action || "Download";
      document.getElementById("art-recommendation").innerText = data.experiment.recommended_action
        ? `Strategy next action: ${data.experiment.recommended_action.toUpperCase()}`
        : "Pending evaluation run.";

      const meta = JSON.parse(data.artifact.meta_json || "{}");
      const btnImg = document.getElementById("btn-view-img");
      const btnVid = document.getElementById("btn-view-vid");
      const btnPkg = document.getElementById("btn-view-pkg");
      if (meta.image) {
        const imgName = meta.image.split("\\").pop().split("/").pop();
        btnImg.href = `/api/media/images/${imgName}`;
        btnImg.style.display = "inline-block";
      } else {
        btnImg.style.display = "none";
      }
      if (data.artifact.file_path) {
        const vidName = data.artifact.file_path.split("\\").pop().split("/").pop();
        btnVid.href = `/api/media/videos/${vidName}`;
        btnVid.style.display = "inline-block";
      } else {
        btnVid.style.display = "none";
      }
      if (meta.deliverable || meta.product_slug) {
        if (meta.product_slug) {
          btnPkg.href = `/products/${encodeURIComponent(meta.product_slug)}/download`;
        } else {
          const pkgName = meta.deliverable.split("\\").pop().split("/").pop();
          btnPkg.href = `/api/media/products/${pkgName}`;
        }
        btnPkg.style.display = "inline-block";
      } else {
        btnPkg.style.display = "none";
      }
    }

    // Portfolio Allocation
    if (data.portfolio && data.portfolio.allocations) {
      document.getElementById("card-portfolio").style.display = "block";
      document.getElementById("port-profile-label").innerText = `Profile: ${data.portfolio.risk_profile} ($${data.portfolio.total_surplus} surplus)`;
      // Defer rendering portfolio until Chart.js is confirmed loaded
      if (typeof Chart !== "undefined") {
        renderPortfolio(data.portfolio.allocations);
      } else {
        setTimeout(() => {
          if (typeof Chart !== "undefined") {
            renderPortfolio(data.portfolio.allocations);
          }
        }, 300);
      }
    }

    // Activity Feed
    renderActivityFeed(data.activity_feed || []);

  } catch (err) {
    console.warn("fetchOverview error:", err);
  } finally {
    isFetchingOverview = false;
  }
}

/* Lightweight Live State Polling */
async function fetchLiveState() {
  if (isFetchingLiveState) return;
  isFetchingLiveState = true;

  try {
    const url = "/api/live-state" + (currentExperimentId ? `?experiment_id=${currentExperimentId}` : "");
    const res = await fetch(url);
    const data = await res.json();

    if (!data.has_experiment) {
      updateExecutionBanner(null, null);
      isFetchingLiveState = false;
      return;
    }

    agentRunsCache = data.agent_runs || [];
    renderNodes(agentRunsCache);
    updateExecutionBanner(data.experiment, data.progression, data.recent_events);
    renderActivityFeed(data.recent_events || []);

    // Detect completion or interruption transition -> trigger overview reload
    if (lastKnownStatus === "running" && data.experiment.status !== "running") {
      lastKnownStatus = data.experiment.status;
      fetchOverview();
    } else {
      lastKnownStatus = data.experiment.status;
    }

  } catch (err) {
    console.warn("fetchLiveState error:", err);
  } finally {
    isFetchingLiveState = false;
  }
}

/* Render Architecture Nodes */
function renderNodes(runs) {
  if (!runs || !Array.isArray(runs)) return;

  runs.forEach(run => {
    const slug = agentNodeMap[run.agent_name];
    if (slug) {
      const nodeEl = document.getElementById(`node-${slug}`);
      const tagEl = document.getElementById(`tag-${slug}`);
      const taskEl = document.getElementById(`task-${slug}`);
      const outputEl = document.getElementById(`output-${slug}`);
      const errEl = document.getElementById(`err-${slug}`);
      const timeEl = document.getElementById(`time-${slug}`);

      if (nodeEl) {
        nodeEl.className = `agent-node ${run.status}`;
      }
      if (tagEl) {
        tagEl.className = `agent-status-tag ${run.status}`;
        tagEl.innerText = formatStatus(run.status);
      }
      if (taskEl) {
        taskEl.innerText = run.input_summary || "Idle";
      }
      if (outputEl) {
        outputEl.innerText = run.output_summary || run.decision_reason || "—";
      }
      if (errEl) {
        if (run.warning_or_error) {
          errEl.innerText = `⚠ ${run.warning_or_error}`;
          errEl.style.display = "block";
        } else {
          errEl.style.display = "none";
        }
      }
      if (timeEl && run.updated_at) {
        const parts = run.updated_at.split(" ");
        timeEl.innerText = parts[1] || parts[0];
      }
    }
  });
}

/* Live Execution Progression Banner */
function updateExecutionBanner(exp, prog, recentEvents) {
  const nameEl = document.getElementById("exec-run-name");
  const pillEl = document.getElementById("exec-status-pill");
  const stageEl = document.getElementById("exec-stage-label");
  const timeEl = document.getElementById("exec-elapsed-time");
  const barEl = document.getElementById("exec-progress-bar");
  const taskEl = document.getElementById("exec-current-task");
  const eventEl = document.getElementById("exec-latest-event");

  if (!exp || !prog) {
    if (nameEl) nameEl.innerText = "Venture Pipeline";
    if (pillEl) {
      pillEl.className = "status-pill";
      pillEl.innerText = "Engine Idle";
    }
    if (stageEl) stageEl.innerText = "Stage 0/9";
    if (timeEl) timeEl.innerText = "Elapsed: 0s";
    if (barEl) barEl.style.width = "0%";
    if (taskEl) taskEl.innerText = "Awaiting venture launch";
    if (eventEl) eventEl.innerText = "No active run";
    return;
  }

  if (nameEl) nameEl.innerText = `${exp.name || "Venture Run"} (#${exp.id})`;
  
  if (pillEl) {
    const isAct = prog.is_actively_running || exp.status === "running";
    if (isAct) {
      pillEl.className = "status-pill running";
      pillEl.innerText = "● Running";
    } else if (exp.status === "completed") {
      pillEl.className = "status-pill connected";
      pillEl.innerText = "✓ Completed";
    } else if (exp.status === "interrupted") {
      pillEl.className = "status-pill waiting";
      pillEl.innerText = "⚠ Interrupted";
    } else if (exp.status === "failed") {
      pillEl.className = "status-pill failed";
      pillEl.innerText = "✕ Failed";
    } else {
      pillEl.className = "status-pill";
      pillEl.innerText = formatStatus(exp.status);
    }
  }

  if (stageEl) stageEl.innerText = `Stage ${prog.completed_stages}/9: ${prog.current_stage}`;
  if (timeEl) timeEl.innerText = `Elapsed: ${prog.elapsed_seconds}s`;
  if (barEl) barEl.style.width = `${prog.progress_pct}%`;
  if (taskEl) taskEl.innerText = prog.current_task ? `Active: ${prog.current_task.slice(0, 70)}` : "All pipeline stages finished.";
  
  // Update Executive Stepper active highlights
  const stages = [
    document.getElementById("step-stage-1"),
    document.getElementById("step-stage-2"),
    document.getElementById("step-stage-3"),
    document.getElementById("step-stage-4")
  ];
  const completed = Number(prog.completed_stages || 0);
  const isCompleted = exp.status === "completed";

  stages.forEach((step, idx) => {
    if (!step) return;
    step.classList.remove("active", "completed");
    // stage index 0: nodes 1-3 (Scout, Strategy, Orchestrator)
    // stage index 1: nodes 4-5 (Content Creator, Quality Checker)
    // stage index 2: nodes 6-7 (Publishing, Measurement)
    // stage index 3: nodes 8-9 (Finance, Portfolio)
    const stageThresholds = [3, 5, 7, 9];
    if (isCompleted || completed >= stageThresholds[idx]) {
      step.classList.add("completed");
    } else if (
      (idx === 0 && completed < 3) ||
      (idx === 1 && completed >= 3 && completed < 5) ||
      (idx === 2 && completed >= 5 && completed < 7) ||
      (idx === 3 && completed >= 7 && completed < 9)
    ) {
      if (exp.status === "running") {
        step.classList.add("active");
      }
    }
  });

  if (eventEl && recentEvents && recentEvents.length > 0) {
    const latest = recentEvents[0];
    eventEl.innerText = `Latest: [${latest.agent_name}] ${latest.message.slice(0, 45)}`;
  }
}

/* Render ChromaDB Important Activity Feed */
async function loadChromaActivities() {
  const feedContainer = document.getElementById("activity-feed");
  if (!feedContainer) return;

  try {
    const res = await fetch("/api/chroma/activities?limit=15");
    const data = await res.json();
    const items = data.activities || [];

    if (items.length === 0) {
      feedContainer.innerHTML = `
        <div style="text-align:center; padding:28px 16px; color:var(--text-muted); font-size:14px;">
          No activities indexed in ChromaDB yet. Generate clips or products to build memory.
        </div>
      `;
      return;
    }

    feedContainer.innerHTML = items.map(item => {
      const cat = escapeHtml(item.category || "activity");
      const title = escapeHtml(item.title || "Event");
      const ts = escapeHtml(item.timestamp || "");
      const doc = escapeHtml(item.document || "");
      const isVideo = cat.includes("clip") || cat.includes("youtube");
      const isProd = cat.includes("product");
      const typeLabel = isVideo ? "CLIP" : (isProd ? "PRODUCT" : "EVENT");

      return `
        <div class="feed-item info" style="padding:10px 12px; margin-bottom:8px; border-radius:8px; background:var(--surface-nested); border:1px solid var(--border-subtle); display:block;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:10px; font-weight:700; letter-spacing:0.5px; background:var(--surface-inset); color:var(--text-muted); padding:2px 6px; border-radius:4px; border:1px solid var(--border-subtle);">${typeLabel}</span>
              <strong style="font-size:13.5px; color:var(--text-primary);">${title}</strong>
            </div>
            <span class="feed-time" style="font-size:11.5px; color:var(--text-subtle);">${ts.split(" ")[1] || ts}</span>
          </div>
          <div style="font-size:12.5px; color:var(--text-secondary); line-height:1.45; word-break:break-word;">${doc}</div>
        </div>
      `;
    }).join("");
  } catch (err) {
    console.warn("loadChromaActivities error:", err);
  }
}

function renderActivityFeed(events) {
  // Defer to ChromaDB real persistent memory
  loadChromaActivities();
}

/* External Platform Integrations UI */
function updateIntegrationBadges(integrations) {
  if (!integrations) return;
  const yt = integrations.youtube || {};
  const ig = integrations.instagram || {};
  const ai = integrations.ai || {};

  const aiPill = document.getElementById("pill-ai-status");
  if (aiPill) {
    if (!ai || ai.active_provider === "unconfigured") {
      aiPill.innerText = "AI: Unconfigured";
      aiPill.className = "status-pill waiting";
    } else {
      let label = "AI: ";
      if (ai.active_provider === "local_deterministic") {
        label += "Local Engine & MCP";
      } else {
        label += `${ai.active_provider.toUpperCase()} (${ai.model || 'Active'})`;
      }
      aiPill.innerText = label;
      aiPill.className = "status-pill connected";
    }
  }

  refreshYouTubeStatus();
  refreshInstagramStatus(ig);
  if (integrations.openshorts) {
    checkClipper(integrations.openshorts);
  } else {
    checkClipper();
  }
}

/* Portfolio Chart Rendering */
function renderPortfolio(allocations) {
  const tableContainer = document.getElementById("portfolio-table");
  if (tableContainer) {
    tableContainer.innerHTML = allocations.map(a => `
      <div style="display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:8px; border-bottom:1px solid var(--border-subtle); padding-bottom:4px;">
        <span><strong>${escapeHtml(a.ticker)}</strong> (${escapeHtml(a.percentage)}%)</span>
        <span>$${parseFloat(a.amount).toFixed(2)}</span>
        <span style="color:var(--text-muted); font-size:11.5px;">${escapeHtml(a.reason)}</span>
      </div>
    `).join("");
  }

  const labels = allocations.map(a => a.ticker);
  const amounts = allocations.map(a => a.amount);

  const canvas = document.getElementById("portfolioChart");
  if (!canvas) return;

  const isDark = document.documentElement.getAttribute("data-theme") === "dark";
  const ctx = canvas.getContext("2d");
  if (portfolioChartInstance) {
    portfolioChartInstance.destroy();
  }
  portfolioChartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [{
        data: amounts,
        backgroundColor: ["#0f172a", "#0d9488", "#2563eb", "#d97706", "#64748b"],
        borderColor: isDark ? "#182234" : "#ffffff",
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: false } }
    }
  });
}

/* Agent Inspector Modal */
function inspectNode(agentName) {
  const run = agentRunsCache.find(r => r.agent_name === agentName || (agentName === 'Content Creator' && r.agent_name === 'Content Creator'));
  document.getElementById("inspect-title").innerText = agentName;
  
  const statusTag = document.getElementById("inspect-status-tag");
  if (statusTag) {
    statusTag.className = `agent-status-tag ${run ? run.status : "waiting"}`;
    statusTag.innerText = run ? formatStatus(run.status) : "Waiting";
  }

  document.getElementById("inspect-input").innerText = run ? (run.input_summary || "None") : "Waiting for pipeline trigger.";
  document.getElementById("inspect-output").innerText = run ? (run.output_summary || "No output recorded.") : "No output recorded.";
  document.getElementById("inspect-reason").innerText = run ? (run.decision_reason || "Deterministic policy.") : "Deterministic decision policy.";

  const errRow = document.getElementById("inspect-error-row");
  const errText = document.getElementById("inspect-error");
  if (run && run.warning_or_error) {
    errText.innerText = run.warning_or_error;
    errRow.style.display = "block";
  } else {
    errRow.style.display = "none";
  }

  const timeEl = document.getElementById("inspect-time");
  if (timeEl) {
    timeEl.innerText = run && run.updated_at ? run.updated_at : "—";
  }

  document.getElementById("inspect-modal").style.display = "flex";
}

/* Chat Assistant Messaging & Safe Markdown Rendering */
let isSendingChat = false;

function getOrCreateConversationId() {
  let convId = localStorage.getItem("mint_conversation_id");
  if (!convId) {
    convId = "conv_" + Date.now() + "_" + Math.random().toString(36).substring(2, 9);
    localStorage.setItem("mint_conversation_id", convId);
  }
  return convId;
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdownSafe(rawText) {
  if (!rawText) return "";

  // 1. Stash fenced code blocks
  const codeBlocks = [];
  let text = String(rawText).replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, function(match, lang, code) {
    const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
    codeBlocks.push({ lang: lang || "", code: code });
    return placeholder;
  });

  // 2. Stash inline code
  const inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, function(match, code) {
    const placeholder = `__INLINE_CODE_${inlineCodes.length}__`;
    inlineCodes.push(code);
    return placeholder;
  });

  // 3. Escape HTML on text content
  text = escapeHtml(text);

  // 4. Headings
  text = text.replace(/^### (.*$)/gim, '<h4 class="chat-md-h3">$1</h4>');
  text = text.replace(/^## (.*$)/gim, '<h3 class="chat-md-h2">$1</h3>');
  text = text.replace(/^# (.*$)/gim, '<h2 class="chat-md-h1">$1</h2>');

  // 5. Bold & Italic
  text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // 6. Safe links (only http/https)
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="chat-link">$1</a>');

  // 7. Bullet lists
  text = text.replace(/^\s*[-*•]\s+(.*$)/gim, '<li class="chat-li">$1</li>');
  text = text.replace(/(<li class="chat-li">[\s\S]*?<\/li>)/g, function(match) {
    return '<ul class="chat-ul">' + match + '</ul>';
  });
  text = text.replace(/<\/ul>\s*<ul class="chat-ul">/g, "");

  // 8. Numbered lists
  text = text.replace(/^\s*(\d+)\.\s+(.*$)/gim, '<li class="chat-oli">$2</li>');
  text = text.replace(/(<li class="chat-oli">[\s\S]*?<\/li>)/g, function(match) {
    return '<ol class="chat-ol">' + match + '</ol>';
  });
  text = text.replace(/<\/ol>\s*<ol class="chat-ol">/g, "");

  // 9. Paragraph spacing
  text = text.replace(/\n\n/g, '<p class="chat-p"></p>');
  text = text.replace(/\n/g, '<br>');

  // 10. Restore inline code
  for (let i = 0; i < inlineCodes.length; i++) {
    const safeCode = escapeHtml(inlineCodes[i]);
    text = text.replace(`__INLINE_CODE_${i}__`, `<code class="chat-inline-code">${safeCode}</code>`);
  }

  // 11. Restore code blocks
  for (let i = 0; i < codeBlocks.length; i++) {
    const safeBlock = escapeHtml(codeBlocks[i].code.trim());
    const langLabel = codeBlocks[i].lang ? `<span class="code-lang-label">${escapeHtml(codeBlocks[i].lang)}</span>` : "";
    text = text.replace(`__CODE_BLOCK_${i}__`, `<div class="chat-code-wrapper">${langLabel}<pre class="chat-pre"><code class="chat-code">${safeBlock}</code></pre></div>`);
  }

  return text;
}

async function loadChatHistory() {
  const chatBox = document.getElementById("chat-box");
  if (!chatBox) return;
  const convId = getOrCreateConversationId();

  try {
    const res = await fetch(`/api/chat/history?conversation_id=${encodeURIComponent(convId)}`);
    if (!res.ok) return;
    const data = await res.json();
    const messages = data.messages || [];

    if (messages.length > 0) {
      chatBox.innerHTML = "";
      for (const m of messages) {
        const bubble = document.createElement("div");
        if (m.sender === "user") {
          bubble.className = "chat-bubble bubble-user";
          bubble.textContent = m.message;
        } else {
          bubble.className = "chat-bubble bubble-mint";
          bubble.innerHTML = renderMarkdownSafe(m.message);
          if (m.action_taken && !["none", "No backend state modified."].includes(m.action_taken)) {
            const actionNote = document.createElement("small");
            actionNote.className = "chat-action-note";
            actionNote.textContent = "Action: " + m.action_taken;
            bubble.appendChild(document.createElement("br"));
            bubble.appendChild(actionNote);
          }
        }
        chatBox.appendChild(bubble);
      }
      chatBox.scrollTop = chatBox.scrollHeight;
    }
  } catch (err) {
    console.warn("Could not load chat history:", err);
  }
}

async function sendChatMessage() {
  const input = document.getElementById("chat-input");
  const chatBox = document.getElementById("chat-box");
  const sendButton = document.getElementById("chat-send-button");
  if (!input || !chatBox || isSendingChat) return;

  const msg = input.value.trim();
  if (!msg) return;

  const convId = getOrCreateConversationId();
  isSendingChat = true;
  if (sendButton) {
    sendButton.disabled = true;
    sendButton.innerText = "Sending…";
  }

  const userBubble = document.createElement("div");
  userBubble.className = "chat-bubble bubble-user";
  userBubble.textContent = msg;
  chatBox.appendChild(userBubble);
  input.value = "";

  const loadingId = "mint-msg-" + Date.now();
  const loadingBubble = document.createElement("div");
  loadingBubble.className = "chat-bubble bubble-mint";
  loadingBubble.id = loadingId;
  loadingBubble.textContent = "Thinking…";
  chatBox.appendChild(loadingBubble);
  chatBox.scrollTop = chatBox.scrollHeight;

  try {
    const response = await fetch("/api/chat/send", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({
        message: msg,
        conversation_id: convId,
        experiment_id: currentExperimentId || null
      })
    });
    const data = await response.json().catch(() => ({}));
    const target = document.getElementById(loadingId);
    if (!target) return;

    if (!response.ok) {
      target.textContent = data.error || `Control Assistant request failed (HTTP ${response.status}).`;
    } else if (data.reply) {
      target.innerHTML = renderMarkdownSafe(data.reply);
      const action = data.action_taken;
      if (action && !["none", "No backend state modified."].includes(action)) {
        const actionNote = document.createElement("small");
        actionNote.className = "chat-action-note";
        actionNote.textContent = "Action: " + action;
        target.appendChild(document.createElement("br"));
        target.appendChild(actionNote);
      }
      if (data.provider_used) {
        const statusLabel = document.getElementById("chat-engine-label");
        if (statusLabel) statusLabel.textContent = data.provider_used;
      }
    } else {
      target.textContent = data.error || "No response was returned. Please retry.";
    }
  } catch (error) {
    const target = document.getElementById(loadingId);
    if (target) {
      target.textContent = "Could not reach MINT. Check that the Flask server is running, then retry.";
    }
  } finally {
    isSendingChat = false;
    if (sendButton) {
      sendButton.disabled = false;
      sendButton.innerText = "Send";
    }
    input.focus();
    chatBox.scrollTop = chatBox.scrollHeight;
  }
}

/* Modal Open/Close Controls */
function openStartModal() {
  document.getElementById("start-modal").style.display = "flex";
}

function closeStartModal() {
  document.getElementById("start-modal").style.display = "none";
}

async function launchExperiment() {
  const goal = document.getElementById("input-goal").value;
  const budget = parseFloat(document.getElementById("input-budget").value);
  const risk = document.getElementById("input-risk").value;

  closeStartModal();

  try {
    const res = await fetch("/api/experiments/create_and_run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: goal, budget_limit: budget, risk_profile: risk })
    });
    const data = await res.json();
    if (data.experiment_id) {
      currentExperimentId = data.experiment_id;
      lastKnownStatus = "running";
      fetchOverview();
      fetchLiveState();
    } else {
      alert("Launch error: " + (data.message || data.error));
    }
  } catch (e) {
    alert("Launch failed: " + e.message);
  }
}

/* YouTube Integration Helpers — IDs and routes match the Flask application. */
async function refreshYouTubeStatus() {
  const pill = document.getElementById("pill-yt");
  const connectBtn = document.getElementById("btn-yt-connect");
  const disconnectBtn = document.getElementById("btn-yt-disconnect");
  const uploadBtn = document.getElementById("btn-yt-upload");
  const testBtn = document.getElementById("btn-yt-test");
  const description = document.getElementById("desc-yt");

  try {
    const response = await fetch("/api/youtube/status", {
      cache: "no-store",
      headers: { "Accept": "application/json" }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok && !data.status) {
      throw new Error(data.error || `YouTube status returned HTTP ${response.status}.`);
    }

    const setVisible = (element, visible) => {
      if (element) element.style.display = visible ? "inline-block" : "none";
    };

    if (data.connected && data.token_valid && data.can_upload) {
      if (pill) {
        pill.innerText = "Connected · Upload ready";
        pill.className = "status-pill connected";
      }
      if (description) description.innerText = data.message || "YouTube OAuth is valid and upload permission is available.";
      setVisible(connectBtn, false);
      setVisible(disconnectBtn, true);
      setVisible(uploadBtn, true);
      setVisible(testBtn, true);
      loadYouTubeChannelInfo(false);
      return;
    }

    if (data.connected && data.token_valid && !data.can_upload) {
      if (pill) {
        pill.innerText = "Permission required";
        pill.className = "status-pill waiting";
      }
      if (description) description.innerText = data.message || "The account is connected but upload permission is missing.";
      setVisible(connectBtn, true);
      setVisible(disconnectBtn, true);
      setVisible(uploadBtn, false);
      setVisible(testBtn, true);
      return;
    }

    const setupRequired = data.status === "setup_required" || data.oauth_configured === false;
    if (pill) {
      pill.innerText = setupRequired ? "OAuth setup required" :
        (data.status === "token_refresh_failed" ? "Token refresh failed" : "Not connected");
      pill.className = setupRequired || data.status === "not_connected" ? "status-pill waiting" : "status-pill failed";
    }
    if (description) description.innerText = data.message || "Connect a YouTube account to enable private uploads.";
    setVisible(connectBtn, true);
    setVisible(disconnectBtn, Boolean(data.status === "token_refresh_failed"));
    setVisible(uploadBtn, false);
    setVisible(testBtn, false);
  } catch (error) {
    if (pill) {
      pill.innerText = "Status unavailable";
      pill.className = "status-pill failed";
    }
    if (description) description.innerText = "Could not reach the YouTube status endpoint. Check that MINT is running and inspect the Flask log.";
    if (connectBtn) connectBtn.style.display = "inline-block";
    if (uploadBtn) uploadBtn.style.display = "none";
    if (testBtn) testBtn.style.display = "none";
  }
}

async function loadYouTubeChannelInfo(forceRefresh = false) {
  const channelInfo = document.getElementById("yt-channel-info");
  const uploadsBox = document.getElementById("yt-uploads-section");
  const uploadsList = document.getElementById("yt-uploads-list");
  const pill = document.getElementById("pill-yt");
  const description = document.getElementById("desc-yt");
  if (!channelInfo) return;

  if (forceRefresh) {
    channelInfo.style.display = "block";
    channelInfo.textContent = "Checking channel access with the YouTube Data API…";
  }

  try {
    const url = `/api/youtube/channel?refresh=${forceRefresh ? "1" : "0"}`;
    const response = await fetch(url, {
      cache: forceRefresh ? "no-store" : "default",
      headers: { "Accept": "application/json" }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Channel endpoint returned HTTP ${response.status}.`);
    }
    const channel = data.channel || {};

    if (!channel.ok) {
      const message = channel.error || "YouTube did not return channel details.";
      channelInfo.style.display = "block";
      channelInfo.textContent = `YouTube API check failed: ${message}`;
      if (pill) {
        pill.innerText = "Channel API error";
        pill.className = "status-pill failed";
      }
      if (description) description.innerText = message;
      if (uploadsBox) uploadsBox.style.display = "none";
      if (uploadsList) uploadsList.replaceChildren();
      return;
    }

    channelInfo.style.display = "block";
    channelInfo.innerHTML = `
      <div style="font-weight:600; font-size:12px; margin-bottom:4px;">
        ✓ ${escapeHtml(channel.channel_name || "YouTube Channel")}
        ${channel.custom_url ? `<span style="color:var(--text-muted); font-weight:400; font-size:11px;">(${escapeHtml(channel.custom_url)})</span>` : ""}
      </div>
      <div style="margin-bottom:6px;">
        <span class="yt-stat-badge">Subs: ${escapeHtml(channel.subscriber_count ?? "—")}</span>
        <span class="yt-stat-badge">Videos: ${escapeHtml(channel.video_count ?? "—")}</span>
        <span class="yt-stat-badge">Views: ${escapeHtml(channel.view_count ?? "—")}</span>
      </div>
      <div style="font-size:10.5px; color:var(--text-subtle);">
        ID: <code>${escapeHtml(channel.channel_id || "—")}</code> · ${channel.cache_hit ? "(cached)" : "(verified API response)"}
      </div>
    `;

    const history = Array.isArray(data.upload_history) ? data.upload_history : [];
    if (uploadsBox && uploadsList && history.length > 0) {
      uploadsBox.style.display = "block";
      uploadsList.innerHTML = history.map(item => `
        <div style="margin-bottom:3px;">
          ${escapeHtml(item.description)} <span style="color:var(--text-subtle);">(${escapeHtml(item.uploaded_at)})</span>
        </div>
      `).join("");
    } else {
      if (uploadsBox) uploadsBox.style.display = "none";
      if (uploadsList) uploadsList.replaceChildren();
    }

    if (pill) {
      pill.innerText = "YouTube API verified";
      pill.className = "status-pill connected";
    }
    if (description) {
      description.innerText = `Channel verified: ${channel.channel_name || "YouTube Channel"}. Upload permission is ${"available after OAuth status verification"}.`;
    }
  } catch (error) {
    const message = "YouTube channel request failed. Check the Flask log for the API error.";
    channelInfo.style.display = "block";
    channelInfo.textContent = message;
    if (pill) {
      pill.innerText = "Channel API error";
      pill.className = "status-pill failed";
    }
    if (description) description.innerText = message;
  }
}

async function testYouTube(forceRefresh = true) {
  const button = document.getElementById("btn-yt-test");
  const previousText = button ? button.innerText : "Refresh Channel Info";
  if (button) {
    button.disabled = true;
    button.innerText = "Checking…";
  }
  try {
    await loadYouTubeChannelInfo(true);
  } finally {
    if (button) {
      button.disabled = false;
      button.innerText = previousText;
    }
  }
}

async function disconnectYouTube() {
  if (!confirm("Disconnect YouTube? This will revoke the stored token.")) return;
  try {
    const res = await fetch("/auth/youtube/disconnect", { method: "POST" });
    const data = await res.json();
    if (data.disconnected) {
      refreshYouTubeStatus();
      const channelInfo = document.getElementById("yt-channel-info");
      if (channelInfo) channelInfo.style.display = "none";
    }
  } catch (e) {
    alert("Disconnect failed: " + e.message);
  }
}

function openUploadModal() {
  const vidBtn = document.getElementById("btn-view-vid");
  if (!vidBtn || vidBtn.style.display === "none") {
    alert("No rendered video available yet. Run a venture experiment first.");
    return;
  }
  const modal = document.getElementById("upload-modal");
  const titleInput = document.getElementById("upload-title");
  const artHook = document.getElementById("art-hook");
  if (titleInput && artHook) {
    titleInput.value = artHook.innerText || "MINT Venture Short";
  }
  modal.style.display = "flex";
}

async function confirmUpload() {
  const title = document.getElementById("upload-title").value.trim();
  const desc = document.getElementById("upload-desc").value.trim();
  const tags = document.getElementById("upload-tags").value.trim().split(",").map(t => t.trim()).filter(Boolean);
  const statusEl = document.getElementById("upload-status");
  const btn = document.getElementById("btn-confirm-upload");

  if (!title) {
    statusEl.innerHTML = "<span style='color:#c0392b;'>Title is required.</span>";
    return;
  }

  btn.disabled = true;
  btn.innerText = "Uploading to YouTube...";
  statusEl.innerHTML = "<em>Sending video to YouTube Data API (Private)...</em>";

  try {
    const res = await fetch("/auth/youtube/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        experiment_id: currentExperimentId,
        title: title,
        description: desc,
        tags: tags,
        confirmed: true
      })
    });
    const data = await res.json();
    if (data.uploaded) {
      statusEl.innerHTML = `✓ Uploaded as <strong>Private</strong>. Video ID: <strong>${escapeHtml(data.video_id)}</strong>. <a href="${escapeHtml(data.url)}" target="_blank" style="color:var(--accent-teal);">Open on YouTube ↗</a>`;
      btn.innerText = "Uploaded!";
      loadYouTubeChannelInfo(true);
    } else {
      statusEl.innerHTML = `<span style='color:#c0392b;'>Upload error: ${escapeHtml(data.error || "Failed")}</span>`;
      btn.disabled = false;
      btn.innerText = "Upload as Private";
    }
  } catch (e) {
    statusEl.innerHTML = `<span style='color:#c0392b;'>Request failed: ${escapeHtml(e.message)}</span>`;
    btn.disabled = false;
    btn.innerText = "Upload as Private";
  }
}

async function deleteSelectedVideo() {
  const sel = document.getElementById("upload-select");
  const filename = sel ? sel.value : "";
  if (!filename) {
    alert("Select a video file to delete.");
    return;
  }
  if (!confirm(`Are you sure you want to delete local video '${filename}'? This cannot be undone.`)) {
    return;
  }
  try {
    const res = await fetch(`/api/youtube/videos/${encodeURIComponent(filename)}`, { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      alert(data.message);
      openUploadModal();
    } else {
      alert("Delete failed: " + (data.error || "Unknown error"));
    }
  } catch (err) {
    alert("Delete request failed: " + err.message);
  }
}

/* Instagram connection status — IDs intentionally match dashboard.html. */
function refreshInstagramStatus(ig) {
  const pill = document.getElementById("pill-ig");
  const desc = document.getElementById("desc-ig");
  const infoBox = document.getElementById("ig-account-info");
  const setupGuide = document.getElementById("ig-setup-guide");
  if (!pill || !desc) return;

  const status = (ig && ig.status) || "connection_error";
  const accountTitle = ig && ig.account_label
    ? ig.account_label
    : (ig && ig.username ? `@${ig.username}` : ((ig && ig.display_name) || "Instagram account"));
  const labels = {
    connected: "Connected · Scope configured",
    connected_no_publish: ig && ig.account_verified ? "Account verified · Publish scope needed" : "Publish permission needed",
    not_configured: "Not configured",
    token_invalid: "Token invalid / expired",
    permission_error: "Permission error",
    unsupported_account: "Account type unsupported",
    connection_error: "Connection error",
    configuration_error: "Configuration error",
    request_error: "Request failed"
  };
  pill.innerText = labels[status] || status.replace(/_/g, " ");
  pill.className = "status-pill " + (
    status === "connected" ? "connected" :
    status === "connected_no_publish" || status === "not_configured" ? "waiting" :
    "failed"
  );
  desc.innerText = (ig && ig.message) || "No diagnostic message was returned by the Instagram status endpoint.";

  if (infoBox) {
    const hasProfile = Boolean(ig && (ig.account_verified || ig.username || ig.account_id));
    if (hasProfile) {
      infoBox.style.display = "block";
      infoBox.innerHTML = `
        <strong>${escapeHtml(accountTitle)}</strong>
        <span>(${escapeHtml(ig.account_type || "Professional account")})</span><br>
        <span class="integration-detail-line">Login: ${escapeHtml(ig.login_method || "not reported")} · API: ${escapeHtml(ig.api_version || "v26.0")}</span><br>
        <span class="integration-detail-line">Publishing scope: ${escapeHtml(ig.required_publish_scope || "not confirmed")}</span>
        ${ig.permission_verified === true ? '<span class="integration-detail-line">Permission verified by Meta</span>' : '<span class="integration-detail-line">Scope declaration is configuration metadata; Meta validates permission when publishing.</span>'}
        <div class="integration-detail-line">${escapeHtml(ig.note || "Instagram video publishing requires a public HTTPS media URL.")}</div>
      `;
    } else {
      infoBox.style.display = "none";
      infoBox.innerHTML = "";
    }
  }

  if (setupGuide) {
    const items = Array.isArray(ig && ig.setup_required) ? ig.setup_required : [];
    setupGuide.style.display = (status === "connected" ? "none" : "block");
    const list = setupGuide.querySelector("ol");
    if (list) {
      list.innerHTML = items.length
        ? items.map(item => `<li>${escapeHtml(item)}</li>`).join("")
        : "<li>Use Check Connection to retrieve a fresh diagnostic.</li>";
    }
  }
}

async function checkInstagram() {
  const pill = document.getElementById("pill-ig");
  const desc = document.getElementById("desc-ig");
  const button = document.getElementById("btn-ig-check");
  if (!pill || !desc) return;

  const previousText = button ? button.innerText : "Check Connection";
  if (button) {
    button.disabled = true;
    button.innerText = "Checking…";
  }
  pill.className = "status-pill";
  pill.innerText = "Checking…";
  desc.innerText = "Checking the configured Instagram login flow against Meta…";

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch("/api/instagram/status?refresh=1", {
      cache: "no-store",
      signal: controller.signal,
      headers: { "Accept": "application/json" }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok && !data.status) {
      throw new Error(data.error || `Status endpoint returned HTTP ${response.status}.`);
    }
    refreshInstagramStatus(data);
  } catch (error) {
    refreshInstagramStatus({
      status: "request_error",
      message: error && error.name === "AbortError"
        ? "Instagram status check timed out after 10 seconds. Check your internet connection and try again."
        : "Could not retrieve Instagram status. Check that MINT is running and inspect the server log."
    });
  } finally {
    clearTimeout(timeoutId);
    if (button) {
      button.disabled = false;
      button.innerText = previousText === "Checking…" ? "Check Connection" : previousText;
    }
  }
}

async function checkClipper(cachedData) {
  const pill = document.getElementById("pill-clipper");
  const desc = document.getElementById("desc-clipper");
  const info = document.getElementById("clipper-info");
  if (!pill) return;

  function renderData(data) {
    const isMcp = data.openshorts_mcp && data.openshorts_mcp.server_running;
    if (isMcp) {
      pill.className = "status-pill connected";
      pill.innerText = "MCP Connected";
      if (desc) desc.innerText = `Connected to OpenShorts MCP server (${data.openshorts_mcp.endpoint || 'http://127.0.0.1:8000/mcp'})`;
      if (info) {
        info.style.display = "block";
        info.innerHTML = `<div><strong>Engine:</strong> OpenShorts MCP (${data.openshorts_mcp.tools_count || 0} tools discovered) &middot; <strong>Local Backup:</strong> Ready</div>`;
      }
    } else {
      pill.className = "status-pill connected";
      pill.innerText = "Local Free Ready";
      if (desc) desc.innerText = "Local Free Engine (faster-whisper CPU + FFmpeg 9:16 transcode) is active. OpenShorts MCP server is offline.";
      if (info) {
        info.style.display = "block";
        info.innerHTML = `<div><strong>Engine:</strong> Local Free (faster-whisper + FFmpeg) &middot; <strong>MCP Server:</strong> Offline at 127.0.0.1:8000</div>`;
      }
    }
  }

  if (cachedData && typeof cachedData === "object" && (cachedData.server_running !== undefined || cachedData.openshorts_mcp)) {
    renderData(cachedData.openshorts_mcp ? cachedData : { openshorts_mcp: cachedData });
    return;
  }

  pill.className = "status-pill";
  pill.innerText = "Checking…";

  try {
    const res = await fetch("/api/youtube/clipper/status");
    const data = await res.json();
    renderData(data);
  } catch (err) {
    pill.className = "status-pill warning";
    pill.innerText = "Local Free";
    if (desc) desc.innerText = "Local Free Clipper available (faster-whisper + FFmpeg).";
  }
}
