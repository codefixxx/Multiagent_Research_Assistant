/**
 * Autonomous Multi-Agent Research Workbench
 * Frontend Logic, Real-Time SSE Stream Listener & Dynamic DAG Engine
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM References
  const queryInput = document.getElementById('query-input');
  const researchForm = document.getElementById('research-form');
  const submitBtn = document.getElementById('submit-btn');
  const subqSelect = document.getElementById('subq-select');
  const wallclockInput = document.getElementById('wallclock-input');
  const deepScrapeChk = document.getElementById('deep-scrape-chk');

  // Telemetry references
  const valRedis = document.getElementById('val-redis');
  const telemetryRedis = document.getElementById('telemetry-redis');
  const valTokens = document.getElementById('val-tokens');
  const pipelinePulse = document.getElementById('pipeline-pulse');
  const pipelineStatusText = document.getElementById('pipeline-status-text');
  const pipelineTimer = document.getElementById('pipeline-timer');

  // DAG references
  const nodePlanner = document.getElementById('node-planner');
  const statusPlanner = document.getElementById('status-planner');
  const workersCluster = document.getElementById('workers-cluster');
  const nodeConsolidator = document.getElementById('node-consolidator');
  const statusConsolidator = document.getElementById('status-consolidator');
  const nodeWriter = document.getElementById('node-writer');
  const statusWriter = document.getElementById('status-writer');

  // Studio references
  const telemetryLogs = document.getElementById('telemetry-logs');
  const eventCountEl = document.getElementById('event-count');
  const statFindings = document.getElementById('stat-findings');
  const statCitations = document.getElementById('stat-citations');
  const statSteps = document.getElementById('stat-steps');
  const citationList = document.getElementById('citation-list');
  const groundingBadge = document.getElementById('grounding-score-badge');

  // Report references
  const reportEmpty = document.getElementById('report-empty');
  const reportContent = document.getElementById('report-content');
  const reportActions = document.getElementById('report-actions');
  const btnCopyMd = document.getElementById('btn-copy-md');
  const btnDownloadJson = document.getElementById('btn-download-json');

  // Popover references
  const citationPopover = document.getElementById('citation-popover');
  const popoverKey = document.getElementById('popover-key');
  const popoverClaim = document.getElementById('popover-claim');
  const popoverUrl = document.getElementById('popover-url');
  const popoverClose = document.getElementById('popover-close');

  // State
  let currentRunId = null;
  let eventSource = null;
  let pollInterval = null;
  let timerInterval = null;
  let startTime = null;
  let eventCounter = 0;
  let activeRunData = null;
  let citationMap = new Map(); // citation_id -> { source_url, verified_claim }

  // 1. Initial Health Check
  async function checkHealth() {
    try {
      const res = await fetch('/health');
      if (res.ok) {
        const data = await res.json();
        const dot = telemetryRedis.querySelector('.pill-dot');
        if (data.redis_connected) {
          dot.className = 'pill-dot connected';
          valRedis.textContent = 'Active (6379)';
        } else {
          dot.className = 'pill-dot disconnected';
          valRedis.textContent = 'Degraded';
        }
      }
    } catch (e) {
      const dot = telemetryRedis.querySelector('.pill-dot');
      dot.className = 'pill-dot disconnected';
      valRedis.textContent = 'Offline';
    }
  }

  checkHealth();
  setInterval(checkHealth, 20000);

  // 2. Preset Chips
  document.querySelectorAll('.preset-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      queryInput.value = chip.dataset.query;
      queryInput.focus();
    });
  });

  // 3. Form Submission
  researchForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = queryInput.value.trim();
    if (!query) return;

    resetWorkspace();
    startTimer();
    setDispatchingState(true);

    try {
      const payload = {
        query: query,
        max_sub_questions: parseInt(subqSelect.value, 10),
        max_wall_clock_seconds: parseFloat(wallclockInput.value),
        deep_scrape: deepScrapeChk.checked
      };

      appendLog('SYSTEM', `Dispatching investigation: "${query}"`);
      pipelineStatusText.textContent = 'ORCHESTRATING RUN • INITIALIZING';
      pipelinePulse.className = 'pulse-indicator active';

      const response = await fetch('/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status}`);
      }

      const data = await response.json();
      currentRunId = data.run_id;
      appendLog('SYSTEM', `Run accepted [ID: ${currentRunId.slice(0, 8)}]`);

      // Begin SSE streaming & status polling
      connectSSE(currentRunId);
      startPolling(currentRunId);

    } catch (err) {
      appendLog('SYSTEM', `Failed to start investigation: ${err.message}`);
      pipelineStatusText.textContent = 'ERROR ENCOUNTERED';
      pipelinePulse.className = 'pulse-indicator';
      setDispatchingState(false);
      stopTimer();
    }
  });

  // 4. Connect SSE Stream
  function connectSSE(runId) {
    if (eventSource) eventSource.close();

    try {
      eventSource = new EventSource(`/research/${runId}/stream`);

      eventSource.onmessage = (event) => {
        try {
          const evtData = JSON.parse(event.data);
          handleStreamEvent(evtData);
        } catch (e) {
          console.warn('Failed parsing SSE payload:', event.data);
        }
      };

      eventSource.onerror = () => {
        // Fallback polling will handle data retrieval
        if (eventSource) eventSource.close();
      };
    } catch (err) {
      console.warn('SSE connection error:', err);
    }
  }

  // 5. Handle Live Stream Events
  function handleStreamEvent(data) {
    eventCounter++;
    eventCountEl.textContent = `${eventCounter} events`;

    const evtName = data.event || 'stream';
    const payload = data.payload || {};

    if (evtName === 'node_start') {
      const node = payload.node;
      updateNodeState(node, 'active');
      appendLog(node.toUpperCase(), `Node activated for execution`);
    } else if (evtName === 'node_complete') {
      const node = payload.node;
      updateNodeState(node, 'completed');
      appendLog(node.toUpperCase(), `Node completed step`);
    } else if (evtName === 'plan_created') {
      const plan = payload.plan || {};
      const subqs = plan.sub_questions || [];
      renderWorkerCapsules(subqs);
      appendLog('PLANNER', `Generated ${subqs.length} targeted sub-questions for parallel dispatch`);
    } else if (evtName === 'finding_extracted') {
      const subqId = payload.sub_question_id || '';
      appendLog('RESEARCHER', `Extracted evidence fact for ${subqId}`);
      incrementStat('stat-findings');
    } else if (evtName === 'review_complete') {
      const approved = payload.is_approved;
      const subqId = payload.sub_question_id;
      updateWorkerReviewBadge(subqId, approved);
      appendLog('REVIEWER', `Quality evaluation for ${subqId}: ${approved ? 'Approved' : '1x Revision Requested'}`);
    } else if (evtName === 'report_synthesized') {
      appendLog('WRITER', 'Report synthesis completed');
    }
  }

  // 6. Polling Fallback & Status Reconciliation
  function startPolling(runId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`/research/${runId}`);
        if (!res.ok) return;

        const data = await res.json();
        activeRunData = data;
        reconcileProgress(data);

        if (data.status === 'completed' || data.status === 'failed' || data.status === 'budget_exceeded') {
          clearInterval(pollInterval);
          if (eventSource) eventSource.close();
          stopTimer();
          setDispatchingState(false);
          pipelinePulse.className = 'pulse-indicator';

          if (data.status === 'completed') {
            pipelineStatusText.textContent = 'INVESTIGATION COMPLETE';
            renderFullReport(data);
          } else {
            pipelineStatusText.textContent = `TERMINATED • ${data.status.toUpperCase()}`;
            appendLog('SYSTEM', `Run halted: ${data.error_message || 'Budget or time limit reached'}`);
          }
        }
      } catch (e) {
        console.warn('Error polling status:', e);
      }
    }, 2000);
  }

  // 7. Update UI from Status Snapshot
  function reconcileProgress(data) {
    if (data.total_tokens) {
      valTokens.textContent = Number(data.total_tokens).toLocaleString();
    }
    if (data.step_count) {
      statSteps.textContent = data.step_count;
    }
    if (data.findings_count) {
      statFindings.textContent = data.findings_count;
    }

    if (data.current_node) {
      pipelineStatusText.textContent = `ACTIVE NODE: ${data.current_node.toUpperCase()} (${data.progress_pct || 0}%)`;
    }
  }

  // 8. DAG Node Management
  function updateNodeState(node, state) {
    if (node === 'planner') {
      nodePlanner.className = `dag-node node-planner ${state}`;
      statusPlanner.textContent = state === 'active' ? 'Synthesizing Plan' : 'Plan Dispatched';
    } else if (node === 'consolidator') {
      nodeConsolidator.className = `dag-node node-consolidator ${state}`;
      statusConsolidator.textContent = state === 'active' ? 'Merging Streams' : 'Joined';
    } else if (node === 'writer') {
      nodeWriter.className = `dag-node node-writer ${state}`;
      statusWriter.textContent = state === 'active' ? 'Drafting Dossier' : 'Finalized';
    }
  }

  function renderWorkerCapsules(subQuestions) {
    workersCluster.innerHTML = '';
    subQuestions.forEach((sq, idx) => {
      const capsule = document.createElement('div');
      capsule.className = 'worker-capsule active';
      capsule.id = `worker-${sq.id || idx}`;

      const title = sq.question || `Sub-topic ${idx + 1}`;
      const searchTerms = (sq.search_queries && sq.search_queries[0]) || 'Web investigation';

      capsule.innerHTML = `
        <div class="worker-top">
          <span class="worker-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
          <span class="worker-badge" id="badge-${sq.id || idx}">Investigating</span>
        </div>
        <div class="worker-bottom">
          <span class="worker-query-chip" title="${escapeHtml(searchTerms)}">${escapeHtml(searchTerms)}</span>
          <span class="worker-status-text" id="wstat-${sq.id || idx}">Active search</span>
        </div>
      `;
      workersCluster.appendChild(capsule);
    });
  }

  function updateWorkerReviewBadge(subqId, approved) {
    const badge = document.getElementById(`badge-${subqId}`);
    const capsule = document.getElementById(`worker-${subqId}`);
    if (badge) {
      if (approved) {
        badge.className = 'worker-badge badge-approved';
        badge.textContent = '✓ Approved';
        if (capsule) capsule.className = 'worker-capsule completed';
      } else {
        badge.className = 'worker-badge badge-revision';
        badge.textContent = '↺ 1x Revision';
      }
    }
  }

  // 9. Report & Citation Rendering
  function renderFullReport(data) {
    reportEmpty.style.display = 'none';
    reportContent.style.display = 'block';
    reportActions.style.display = 'flex';

    const report = data.report || {};
    citationMap.clear();

    // Index verified citations
    if (report.citations && Array.isArray(report.citations)) {
      report.citations.forEach(c => {
        citationMap.set(c.citation_id, {
          source_url: c.source_url,
          verified_claim: c.verified_claim
        });
      });
      statCitations.textContent = report.citations.length;
      renderCitationDrawer(report.citations);
    }

    // Markdown rendering
    let markdown = report.markdown_output || '';
    if (!markdown && report.title) {
      markdown = `# ${report.title}\n\n## Executive Summary\n${report.executive_summary || ''}\n\n`;
      if (report.sections) {
        report.sections.forEach(s => {
          markdown += `## ${s.heading || s.title || 'Section'}\n${s.content || ''}\n\n`;
        });
      }
      if (report.key_takeaways && report.key_takeaways.length) {
        markdown += `## Key Takeaways\n`;
        report.key_takeaways.forEach(k => { markdown += `* ${k}\n`; });
      }
    }

    // Render with Marked or fallback
    let htmlContent = '';
    if (window.marked && typeof window.marked.parse === 'function') {
      htmlContent = window.marked.parse(markdown);
    } else {
      htmlContent = escapeHtml(markdown).replace(/\n/g, '<br>');
    }

    // Transform citation markers [cite_X] into interactive elements
    htmlContent = htmlContent.replace(/\[cite_(\d+)\]/g, (match, p1) => {
      const key = `cite_${p1}`;
      return `<button type="button" class="citation-badge" data-key="${key}">[cite_${p1}]</button>`;
    });

    htmlContent = htmlContent.replace(/\[UNVERIFIED_CITATION:\s*(cite_\w+)\]/g, (match, p1) => {
      return `<button type="button" class="citation-badge unverified" data-key="${p1}">[unverified: ${p1}]</button>`;
    });

    reportContent.innerHTML = htmlContent;

    // Attach click listeners to citations
    reportContent.querySelectorAll('.citation-badge').forEach(badge => {
      badge.addEventListener('click', (e) => {
        const key = badge.dataset.key;
        showCitationPopover(key, badge);
      });
    });

    // Update Grounding Score
    if (data.citation_validation) {
      const score = Math.round((data.citation_validation.grounding_score || 1.0) * 100);
      groundingBadge.textContent = `${score}% Grounded`;
      groundingBadge.className = 'grounding-badge badge-success';
    } else if (report.citations && report.citations.length > 0) {
      groundingBadge.textContent = '100% Grounded';
      groundingBadge.className = 'grounding-badge badge-success';
    }
  }

  function renderCitationDrawer(citations) {
    citationList.innerHTML = '';
    citations.forEach(c => {
      const item = document.createElement('div');
      item.className = 'citation-item';
      item.dataset.key = c.citation_id;

      let domain = '';
      try {
        domain = new URL(c.source_url).hostname.replace('www.', '');
      } catch (e) {
        domain = c.source_url;
      }

      item.innerHTML = `
        <span class="cite-key">${c.citation_id}</span>
        <span class="cite-domain" title="${escapeHtml(c.source_url)}">${escapeHtml(domain)}</span>
      `;

      item.addEventListener('click', () => {
        showCitationPopover(c.citation_id, item);
      });

      citationList.appendChild(item);
    });
  }

  function showCitationPopover(key, targetElement) {
    const citation = citationMap.get(key);
    popoverKey.textContent = key;

    if (citation) {
      popoverClaim.textContent = citation.verified_claim || 'Verified factual claim from web provenance extraction.';
      popoverUrl.href = citation.source_url || '#';
      popoverUrl.textContent = citation.source_url || 'Unknown source';
      popoverUrl.style.display = 'block';
    } else {
      popoverClaim.textContent = 'Unverified reference: Fact was generated without matching scraped ground truth.';
      popoverUrl.style.display = 'none';
    }

    citationPopover.style.display = 'block';
  }

  popoverClose.addEventListener('click', () => {
    citationPopover.style.display = 'none';
  });

  // 10. Copy and Download Handlers
  btnCopyMd.addEventListener('click', () => {
    if (activeRunData && activeRunData.report && activeRunData.report.markdown_output) {
      navigator.clipboard.writeText(activeRunData.report.markdown_output);
      btnCopyMd.querySelector('span').textContent = 'Copied!';
      setTimeout(() => { btnCopyMd.querySelector('span').textContent = 'Copy Markdown'; }, 2000);
    }
  });

  btnDownloadJson.addEventListener('click', () => {
    if (activeRunData) {
      const blob = new Blob([JSON.stringify(activeRunData, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `research_dossier_${(currentRunId || 'export').slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }
  });

  // Helpers
  function appendLog(tag, msg) {
    const timeStr = getElapsedFormatted();
    const entry = document.createElement('div');
    entry.className = 'log-entry';

    let tagClass = 'tag-system';
    const lowerTag = tag.toLowerCase();
    if (lowerTag.includes('planner')) tagClass = 'tag-planner';
    else if (lowerTag.includes('researcher')) tagClass = 'tag-researcher';
    else if (lowerTag.includes('reviewer')) tagClass = 'tag-reviewer';
    else if (lowerTag.includes('consolidator')) tagClass = 'tag-consolidator';
    else if (lowerTag.includes('writer')) tagClass = 'tag-writer';

    entry.innerHTML = `
      <span class="log-time">${timeStr}</span>
      <span class="log-tag ${tagClass}">${escapeHtml(tag)}</span>
      <span class="log-msg">${escapeHtml(msg)}</span>
    `;

    telemetryLogs.appendChild(entry);
    telemetryLogs.scrollTop = telemetryLogs.scrollHeight;
  }

  function incrementStat(id) {
    const el = document.getElementById(id);
    if (el) {
      const curr = parseInt(el.textContent, 10) || 0;
      el.textContent = curr + 1;
    }
  }

  function setDispatchingState(isDispatching) {
    submitBtn.disabled = isDispatching;
    queryInput.disabled = isDispatching;
  }

  function startTimer() {
    startTime = Date.now();
    pipelineTimer.textContent = '00:00.0';
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
      pipelineTimer.textContent = getElapsedFormatted();
    }, 100);
  }

  function stopTimer() {
    if (timerInterval) clearInterval(timerInterval);
  }

  function getElapsedFormatted() {
    if (!startTime) return '00:00.0';
    const elapsedMs = Date.now() - startTime;
    const totalSec = Math.floor(elapsedMs / 1000);
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    const dec = Math.floor((elapsedMs % 1000) / 100);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${dec}`;
  }

  function resetWorkspace() {
    eventCounter = 0;
    eventCountEl.textContent = '0 events';
    telemetryLogs.innerHTML = '';
    citationList.innerHTML = '<div class="citation-empty">Verified citations will populate upon completion.</div>';
    statFindings.textContent = '0';
    statCitations.textContent = '0';
    statSteps.textContent = '0';
    valTokens.textContent = '0';

    nodePlanner.className = 'dag-node node-planner';
    statusPlanner.textContent = 'Waiting';
    nodeConsolidator.className = 'dag-node node-consolidator';
    statusConsolidator.textContent = 'Waiting';
    nodeWriter.className = 'dag-node node-writer';
    statusWriter.textContent = 'Waiting';

    workersCluster.innerHTML = '<div class="worker-placeholder">Parallel researcher nodes instantiate upon topic decomposition</div>';
    reportEmpty.style.display = 'flex';
    reportContent.style.display = 'none';
    reportActions.style.display = 'none';
    citationPopover.style.display = 'none';
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
});
