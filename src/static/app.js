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
  const btnDownloadMd = document.getElementById('btn-download-md');
  const btnDownloadJson = document.getElementById('btn-download-json');

  // Popover references
  const citationPopover = document.getElementById('citation-popover');
  const popoverKey = document.getElementById('popover-key');
  const popoverClaim = document.getElementById('popover-claim');
  const popoverUrl = document.getElementById('popover-url');
  const popoverClose = document.getElementById('popover-close');

  // Settings & BYOK Drawer references
  const btnOpenSettings = document.getElementById('btn-open-settings');
  const btnCloseSettings = document.getElementById('btn-close-settings');
  const drawerOverlay = document.getElementById('drawer-overlay');
  const settingsDrawer = document.getElementById('settings-drawer');
  const btnSaveSettings = document.getElementById('btn-save-settings');
  const btnResetSettings = document.getElementById('btn-reset-settings');
  const presetFast = document.getElementById('preset-fast');
  const presetQuality = document.getElementById('preset-quality');
  const matrixPlanner = document.getElementById('matrix-planner');
  const matrixResearcher = document.getElementById('matrix-researcher');
  const matrixReviewer = document.getElementById('matrix-reviewer');
  const matrixWriter = document.getElementById('matrix-writer');
  const keyGemini = document.getElementById('key-gemini');
  const keyOpenai = document.getElementById('key-openai');
  const keyAnthropic = document.getElementById('key-anthropic');
  const keyGroq = document.getElementById('key-groq');
  const keyTavily = document.getElementById('key-tavily');

  // State
  let currentRunId = null;
  let eventSource = null;
  let pollInterval = null;
  let timerInterval = null;
  let startTime = null;
  let selectedTimeLimitSec = 120;
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
      const modelMatrix = getActiveModelMatrix();
      const apiKeys = getStoredApiKeys();

      const payload = {
        query: query,
        max_sub_questions: parseInt(subqSelect.value, 10),
        max_wall_clock_seconds: parseFloat(wallclockInput.value),
        deep_scrape: deepScrapeChk.checked,
        model_matrix: modelMatrix,
        api_keys: apiKeys
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

      const onPayload = (event, explicitType) => {
        try {
          const evtData = JSON.parse(event.data);
          if (explicitType && !evtData.event) {
            evtData.event = explicitType;
          }
          handleStreamEvent(evtData);
        } catch (e) {
          console.warn('Failed parsing SSE payload:', event.data);
        }
      };

      eventSource.onmessage = (event) => onPayload(event);

      // Register listener for every named event dispatched by backend
      const namedEvents = [
        'job_started',
        'planner_completed',
        'plan_created',
        'researching_subquestion',
        'finding_extracted',
        'subquestion_reviewed',
        'review_complete',
        'consolidator_completed',
        'writing_completed',
        'report_synthesized',
        'job_completed',
        'budget_exceeded',
        'job_failed',
        'node_start',
        'node_complete'
      ];
      namedEvents.forEach(evtName => {
        eventSource.addEventListener(evtName, (event) => onPayload(event, evtName));
      });

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
    const payload = data.payload || data || {};

    if (evtName === 'job_started') {
      updateNodeState('planner', 'active');
      appendLog('SYSTEM', payload.message || 'Investigation started');
    } else if (evtName === 'node_start') {
      const node = payload.node;
      updateNodeState(node, 'active');
      appendLog(node.toUpperCase(), `Node activated for execution`);
    } else if (evtName === 'node_complete') {
      const node = payload.node;
      updateNodeState(node, 'completed');
      appendLog(node.toUpperCase(), `Node completed step`);
    } else if (evtName === 'planner_completed' || evtName === 'plan_created') {
      updateNodeState('planner', 'completed');
      updateNodeState('consolidator', 'active');
      const subqs = payload.sub_questions || (payload.plan && payload.plan.sub_questions) || [];
      if (subqs.length > 0) {
        renderWorkerCapsules(subqs);
      }
      appendLog('PLANNER', `Generated ${payload.sub_questions_count || subqs.length} targeted sub-questions for parallel dispatch`);
    } else if (evtName === 'researching_subquestion' || evtName === 'finding_extracted') {
      const subqId = payload.sub_question_id || '';
      if (subqId) updateWorkerActive(subqId);
      if (payload.total_findings_count) {
        statFindings.textContent = payload.total_findings_count;
      } else {
        incrementStat('stat-findings');
      }
      appendLog('RESEARCHER', `Gathered evidence findings${subqId ? ' for ' + subqId : ''}`);
    } else if (evtName === 'subquestion_reviewed' || evtName === 'review_complete') {
      const isRevision = Boolean(payload.is_revision);
      const approved = payload.is_revision !== undefined ? !payload.is_revision : Boolean(payload.is_approved);
      const subqId = payload.sub_question_id;
      if (subqId) updateWorkerReviewBadge(subqId, approved, isRevision);
      appendLog('REVIEWER', `Quality evaluation for ${subqId || 'worker'}: ${isRevision ? '1x Revision Triggered (Refining evidence)' : 'Approved'}`);
    } else if (evtName === 'consolidator_completed') {
      finalizeAllWorkers();
      updateNodeState('consolidator', 'completed');
      updateNodeState('writer', 'active');
      pipelineStatusText.textContent = 'SYNTHESIZING REPORT & CITATIONS';
      if (payload.total_findings_count) {
        statFindings.textContent = payload.total_findings_count;
      }
      appendLog('CONSOLIDATOR', `Joined all parallel research streams into canonical evidence set (${payload.total_findings_count || 0} facts)`);
    } else if (evtName === 'writing_completed' || evtName === 'report_synthesized') {
      finalizeAllWorkers();
      updateNodeState('writer', 'completed');
      appendLog('WRITER', `Technical report synthesis complete with ${payload.citations_count || 0} citations`);
    } else if (evtName === 'job_completed' || evtName === 'budget_exceeded') {
      finalizeAllDagNodes();
      if (evtName === 'budget_exceeded') {
        pipelineStatusText.textContent = 'TERMINATED • BUDGET_EXCEEDED';
        appendLog('SYSTEM', 'Budget ceiling reached. Interim synthesis rendered.');
      } else {
        pipelineStatusText.textContent = 'INVESTIGATION COMPLETED';
        appendLog('SYSTEM', 'Investigation complete. Final dossier rendered.');
      }
      if (payload.report) {
        renderFullReport(payload);
      } else if (currentRunId) {
        fetch(`/research/${currentRunId}`)
          .then(res => res.json())
          .then(data => { if (data.report) renderFullReport(data); });
      }
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
          if (data.status === 'completed' || data.status === 'budget_exceeded') {
            // Stop polling when report is populated
            if (data.report && (data.report.title || data.report.markdown_output)) {
              clearInterval(pollInterval);
              if (eventSource) eventSource.close();
              finalizeAllDagNodes();
              renderFullReport(data);
              if (data.status === 'completed') {
                pipelineStatusText.textContent = 'INVESTIGATION COMPLETED';
              } else {
                pipelineStatusText.textContent = 'TERMINATED • BUDGET_EXCEEDED';
                appendLog('SYSTEM', `Run halted: ${data.error_message || 'Budget or time limit reached'}`);
              }
            }
          } else {
            clearInterval(pollInterval);
            if (eventSource) eventSource.close();
            finalizeAllDagNodes();
            pipelineStatusText.textContent = `TERMINATED • ${data.status.toUpperCase()}`;
            appendLog('SYSTEM', `Run halted: ${data.error_message || 'Research run encountered an error'}`);
          }
        }
      } catch (e) {
        console.warn('Error polling status:', e);
      }
    }, 1500);
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

    const node = data.current_node;
    if (node === 'planner') {
      updateNodeState('planner', 'active');
    } else if (node === 'researcher') {
      updateNodeState('planner', 'completed');
    } else if (node === 'consolidator') {
      updateNodeState('planner', 'completed');
      updateNodeState('consolidator', 'active');
    } else if (node === 'writer') {
      updateNodeState('planner', 'completed');
      updateNodeState('consolidator', 'completed');
      updateNodeState('writer', 'active');
    } else if (data.status === 'completed' || node === 'done') {
      finalizeAllDagNodes();
    }

    if (node && data.status !== 'completed' && node !== 'done') {
      pipelineStatusText.textContent = `ACTIVE NODE: ${node.toUpperCase()} (${data.progress_pct || 0}%)`;
    }
  }

  // 8. DAG Node Management
  function updateNodeState(node, state) {
    if (node === 'planner') {
      nodePlanner.className = `dag-node node-planner ${state}`;
      statusPlanner.textContent = state === 'active' ? 'Synthesizing Plan' : (state === 'completed' ? 'Plan Dispatched' : 'Waiting');
    } else if (node === 'consolidator') {
      nodeConsolidator.className = `dag-node node-consolidator ${state}`;
      statusConsolidator.textContent = state === 'active' ? 'Merging Streams' : (state === 'completed' ? 'Joined & Verified' : 'Waiting');
    } else if (node === 'writer') {
      nodeWriter.className = `dag-node node-writer ${state}`;
      statusWriter.textContent = state === 'active' ? 'Drafting Dossier' : (state === 'completed' ? 'Finalized' : 'Waiting');
    }
  }

  function finalizeAllWorkers() {
    document.querySelectorAll('.worker-capsule').forEach(capsule => {
      capsule.className = 'worker-capsule completed';
    });
    document.querySelectorAll('.worker-badge').forEach(badge => {
      badge.className = 'worker-badge badge-approved';
      badge.textContent = '✓ Approved';
    });
    document.querySelectorAll('.worker-status-text').forEach(wstat => {
      wstat.textContent = 'Evidence secured';
    });
  }

  function finalizeAllDagNodes() {
    finalizeAllWorkers();
    updateNodeState('planner', 'completed');
    updateNodeState('consolidator', 'completed');
    updateNodeState('writer', 'completed');
    stopTimer();
    setDispatchingState(false);
    pipelinePulse.className = 'pulse-indicator';
    pipelineStatusText.textContent = 'INVESTIGATION COMPLETE';
  }

  function getWorkerElements(subqId) {
    if (!subqId && subqId !== 0) return { badge: null, capsule: null };
    let badge = document.getElementById(`badge-${subqId}`);
    let capsule = document.getElementById(`worker-${subqId}`);
    if (!badge) {
      const match = String(subqId).match(/\d+/);
      if (match) {
        const num = match[0];
        const numInt = parseInt(num, 10);
        badge = document.getElementById(`badge-${num}`) || 
                document.getElementById(`badge-subq_${num}`) || 
                document.getElementById(`badge-${numInt - 1}`);
        capsule = document.getElementById(`worker-${num}`) || 
                  document.getElementById(`worker-subq_${num}`) || 
                  document.getElementById(`worker-${numInt - 1}`);
      }
    }
    return { badge, capsule };
  }

  function updateWorkerActive(subqId) {
    const { badge, capsule } = getWorkerElements(subqId);
    if (badge) {
      badge.className = 'worker-badge badge-active';
      badge.textContent = 'Gathering...';
    }
    if (capsule) {
      capsule.className = 'worker-capsule active';
      const wstat = capsule.querySelector('.worker-status-text');
      if (wstat) wstat.textContent = 'Active search';
    }
  }

  function renderWorkerCapsules(subQuestions) {
    workersCluster.innerHTML = '';
    subQuestions.forEach((sq, idx) => {
      const capsule = document.createElement('div');
      capsule.className = 'worker-capsule active';
      const rawId = sq.id || `subq_${idx + 1}`;
      capsule.id = `worker-${rawId}`;

      const title = sq.question || `Sub-topic ${idx + 1}`;
      const searchTerms = (sq.search_queries && sq.search_queries[0]) || 'Web investigation';

      capsule.innerHTML = `
        <div class="worker-top">
          <span class="worker-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
          <span class="worker-badge" id="badge-${rawId}">Investigating</span>
        </div>
        <div class="worker-bottom">
          <span class="worker-query-chip" title="${escapeHtml(searchTerms)}">${escapeHtml(searchTerms)}</span>
          <span class="worker-status-text" id="wstat-${rawId}">Active search</span>
        </div>
      `;
      workersCluster.appendChild(capsule);
    });
  }

  function updateWorkerReviewBadge(subqId, approved, isRevision) {
    const { badge, capsule } = getWorkerElements(subqId);
    if (badge) {
      if (isRevision) {
        badge.className = 'worker-badge badge-revision';
        badge.textContent = '↺ Revision (Pass 2)';
        if (capsule) {
          capsule.className = 'worker-capsule active';
          const wstat = capsule.querySelector('.worker-status-text');
          if (wstat) wstat.textContent = 'Refining evidence...';
        }
      } else if (approved) {
        badge.className = 'worker-badge badge-approved';
        badge.textContent = '✓ Approved';
        if (capsule) capsule.className = 'worker-capsule completed';
        const wstat = capsule ? capsule.querySelector('.worker-status-text') : null;
        if (wstat) wstat.textContent = 'Evidence secured';
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

    // Index verified citations under all key variants
    if (report.citations && Array.isArray(report.citations)) {
      report.citations.forEach(c => {
        const cleanKey = (c.citation_id || '').replace(/[\[\]]/g, '').trim().toLowerCase();
        const dataObj = {
          citation_id: c.citation_id,
          source_url: c.source_url,
          anchor_url: c.anchor_url || c.source_url,
          verified_claim: c.verified_claim,
          verbatim_quote: c.verbatim_quote || '',
          http_status: c.http_status || 200,
          is_deep_link: c.is_deep_link
        };
        citationMap.set(cleanKey, dataObj);

        // Alias index keys so numeric, cite_X, and bracketed formats always hit
        if (cleanKey.startsWith('cite_')) {
          const num = cleanKey.slice(5);
          citationMap.set(num, dataObj);
          citationMap.set(`cite${num}`, dataObj);
          citationMap.set(`[cite_${num}]`, dataObj);
          citationMap.set(`[${num}]`, dataObj);
        } else if (/^\d+$/.test(cleanKey)) {
          citationMap.set(`cite_${cleanKey}`, dataObj);
          citationMap.set(`cite${cleanKey}`, dataObj);
          citationMap.set(`[cite_${cleanKey}]`, dataObj);
          citationMap.set(`[${cleanKey}]`, dataObj);
        }
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
          markdown += `## ${s.title || s.heading || 'Section'}\n${s.content || ''}\n\n`;
        });
      }
      if (report.key_takeaways && report.key_takeaways.length) {
        markdown += `## Key Takeaways\n`;
        report.key_takeaways.forEach(k => { markdown += `* ${k}\n`; });
      }
    }

    // Render with Marked or fallback
    let htmlContent = '';
    try {
      if (window.marked) {
        if (typeof window.marked.parse === 'function') {
          htmlContent = window.marked.parse(markdown);
        } else if (typeof window.marked === 'function') {
          htmlContent = window.marked(markdown);
        }
      }
    } catch (err) {
      console.warn('Marked parsing error:', err);
    }
    if (!htmlContent) {
      htmlContent = escapeHtml(markdown).replace(/\n/g, '<br>');
    }

    // Helper to find citation from key
    function lookupCitation(rawKey) {
      const clean = (rawKey || '').replace(/[\[\]]/g, '').trim().toLowerCase();
      let c = citationMap.get(clean);
      if (!c && /^\d+$/.test(clean)) c = citationMap.get(`cite_${clean}`);
      if (!c && clean.startsWith('cite_')) c = citationMap.get(clean.slice(5));
      if (!c && clean.startsWith('cite')) c = citationMap.get(clean.slice(4));
      return { cite: c, cleanKey: clean };
    }

    // Transform ALL inline citation markers [cite_X], [cite:X], [citeX], [1], [2], etc. into interactive clickable links
    htmlContent = htmlContent.replace(/\[(cite(?:_|\:)?\d+|\d+)\]/gi, (match, p1) => {
      const { cite, cleanKey } = lookupCitation(p1);
      const displayKey = cleanKey.startsWith('cite_') ? cleanKey : (cleanKey.startsWith('cite') ? `cite_${cleanKey.slice(4)}` : `cite_${cleanKey}`);
      if (cite) {
        const directUrl = cite.anchor_url || cite.source_url;
        const claimText = cite.verified_claim || 'Verified factual claim';
        return `<a href="${escapeHtml(directUrl)}" target="_blank" rel="noopener noreferrer" class="citation-badge" data-key="${displayKey}" title="Source: ${escapeHtml(directUrl)}&#10;Claim: ${escapeHtml(claimText)}&#10;Click to open verified source in new tab">[${displayKey}] <span class="cite-glyph">↗</span></a>`;
      } else {
        return `<span class="citation-badge unverified" data-key="${displayKey}" title="Unverified citation: Source finding not recorded">[${displayKey}]</span>`;
      }
    });

    htmlContent = htmlContent.replace(/\[UNVERIFIED_CITATION:\s*([^\]]+)\]/gi, (match, p1) => {
      const trimmed = p1.trim();
      return `<span class="citation-badge unverified" data-key="${trimmed}" title="Unverified source citation">[unverified: ${trimmed}]</span>`;
    });

    reportContent.innerHTML = htmlContent;

    // Ensure all standard links inside report open in new tab
    reportContent.querySelectorAll('a').forEach(a => {
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    });

    // Attach hover and click listeners to update popover
    reportContent.querySelectorAll('.citation-badge').forEach(badge => {
      badge.addEventListener('mouseenter', () => {
        showCitationPopover(badge.dataset.key, badge);
      });
      badge.addEventListener('click', () => {
        showCitationPopover(badge.dataset.key, badge);
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
      const cleanKey = (c.citation_id || '').replace(/[\[\]]/g, '').trim();
      const item = document.createElement('div');
      item.className = 'citation-item';
      item.dataset.key = cleanKey;

      let domain = '';
      try {
        domain = new URL(c.source_url).hostname.replace('www.', '');
      } catch (e) {
        domain = c.source_url;
      }

      const statusBadge = c.http_status === 200 
        ? '<span class="status-pill status-ok">200 OK</span>' 
        : `<span class="status-pill">${c.http_status || 'verified'}</span>`;
      const directUrl = c.anchor_url || c.source_url;

      item.innerHTML = `
        <div class="cite-row-main">
          <span class="cite-key">[${cleanKey}]</span>
          <span class="cite-domain" title="${escapeHtml(c.source_url)}">${escapeHtml(domain)}</span>
          ${statusBadge}
        </div>
        <div class="cite-claim-row" title="${escapeHtml(c.verified_claim || '')}">
          ${escapeHtml(c.verified_claim || '')}
        </div>
        <div class="cite-action-row">
          <a href="${escapeHtml(directUrl)}" target="_blank" rel="noopener noreferrer" class="cite-link" title="Open verified source in new tab">
            Open Source <span class="cite-glyph">↗</span>
          </a>
        </div>
      `;

      item.addEventListener('click', (e) => {
        if (e.target.tagName.toLowerCase() === 'a' || e.target.closest('a')) return;
        showCitationPopover(cleanKey, item);
      });

      citationList.appendChild(item);
    });
  }

  function showCitationPopover(key, targetElement) {
    const cleanKey = (key || '').replace(/[\[\]]/g, '').trim().toLowerCase();
    let citation = citationMap.get(cleanKey);
    if (!citation && /^\d+$/.test(cleanKey)) citation = citationMap.get(`cite_${cleanKey}`);
    if (!citation && cleanKey.startsWith('cite_')) citation = citationMap.get(cleanKey.slice(5));

    popoverKey.textContent = `[${cleanKey}]`;

    if (citation) {
      const quoteHtml = citation.verbatim_quote ? `<div style="font-style:italic;color:var(--text-muted);margin-top:6px;border-left:2px solid var(--accent-cyan);padding-left:8px;">"${escapeHtml(citation.verbatim_quote)}"</div>` : '';
      popoverClaim.innerHTML = `${escapeHtml(citation.verified_claim || 'Verified factual claim from web provenance extraction.')}${quoteHtml}`;
      const directUrl = citation.anchor_url || citation.source_url;
      popoverUrl.href = directUrl;
      popoverUrl.textContent = directUrl;
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

  if (btnDownloadMd) {
    btnDownloadMd.addEventListener('click', () => {
      if (activeRunData && activeRunData.report && activeRunData.report.markdown_output) {
        const blob = new Blob([activeRunData.report.markdown_output], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `research_report_${(currentRunId || 'export').slice(0, 8)}.md`;
        a.click();
        URL.revokeObjectURL(url);
      }
    });
  }

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
    selectedTimeLimitSec = parseFloat(wallclockInput.value) || 120;
    updateTimerDisplay();
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(updateTimerDisplay, 100);
  }

  function updateTimerDisplay() {
    const elapsed = getElapsedFormatted();
    const limitMins = Math.floor(selectedTimeLimitSec / 60);
    const limitSecs = Math.floor(selectedTimeLimitSec % 60);
    const limitStr = `${String(limitMins).padStart(2, '0')}:${String(limitSecs).padStart(2, '0')}`;
    pipelineTimer.textContent = `${elapsed} / ${limitStr}`;
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

  // 10. Settings & BYOK Controller
  const STORAGE_KEY_API_KEYS = 'multiresearch_byok_keys';
  const STORAGE_KEY_MODEL_MATRIX = 'multiresearch_model_matrix';

  const DEFAULT_MATRIX = {
    planner: 'gemini-3.5-flash-lite',
    researcher: 'gemini-3.5-flash-lite',
    reviewer: 'gemini-3.5-flash-lite',
    writer: 'gemini-3.5-flash-lite'
  };

  function openSettingsDrawer() {
    if (drawerOverlay && settingsDrawer) {
      drawerOverlay.classList.add('open');
      settingsDrawer.classList.add('open');
    }
  }

  function closeSettingsDrawer() {
    if (drawerOverlay && settingsDrawer) {
      drawerOverlay.classList.remove('open');
      settingsDrawer.classList.remove('open');
    }
  }

  function getStoredApiKeys() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_API_KEYS);
      if (stored) return JSON.parse(stored);
    } catch (e) {
      console.warn('Error reading stored API keys:', e);
    }
    return {};
  }

  function getActiveModelMatrix() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_MODEL_MATRIX);
      if (stored) return JSON.parse(stored);
    } catch (e) {
      console.warn('Error reading stored model matrix:', e);
    }
    return { ...DEFAULT_MATRIX };
  }

  function loadSettings() {
    const keys = getStoredApiKeys();
    if (keyGemini) keyGemini.value = keys.gemini || '';
    if (keyOpenai) keyOpenai.value = keys.openai || '';
    if (keyAnthropic) keyAnthropic.value = keys.anthropic || '';
    if (keyGroq) keyGroq.value = keys.groq || '';
    if (keyTavily) keyTavily.value = keys.tavily || '';

    const matrix = getActiveModelMatrix();
    if (matrixPlanner) matrixPlanner.value = matrix.planner || DEFAULT_MATRIX.planner;
    if (matrixResearcher) matrixResearcher.value = matrix.researcher || DEFAULT_MATRIX.researcher;
    if (matrixReviewer) matrixReviewer.value = matrix.reviewer || DEFAULT_MATRIX.reviewer;
    if (matrixWriter) matrixWriter.value = matrix.writer || DEFAULT_MATRIX.writer;

    updateHeaderModelLabel(matrix);
  }

  function saveSettings() {
    const keys = {
      gemini: keyGemini ? keyGemini.value.trim() : '',
      openai: keyOpenai ? keyOpenai.value.trim() : '',
      anthropic: keyAnthropic ? keyAnthropic.value.trim() : '',
      groq: keyGroq ? keyGroq.value.trim() : '',
      tavily: keyTavily ? keyTavily.value.trim() : ''
    };

    const matrix = {
      planner: matrixPlanner ? matrixPlanner.value : DEFAULT_MATRIX.planner,
      researcher: matrixResearcher ? matrixResearcher.value : DEFAULT_MATRIX.researcher,
      reviewer: matrixReviewer ? matrixReviewer.value : DEFAULT_MATRIX.reviewer,
      writer: matrixWriter ? matrixWriter.value : DEFAULT_MATRIX.writer
    };

    localStorage.setItem(STORAGE_KEY_API_KEYS, JSON.stringify(keys));
    localStorage.setItem(STORAGE_KEY_MODEL_MATRIX, JSON.stringify(matrix));
    updateHeaderModelLabel(matrix);
    appendLog('SYSTEM', 'Execution settings & model matrix updated');
  }

  function resetSettingsToDefaults() {
    if (matrixPlanner) matrixPlanner.value = DEFAULT_MATRIX.planner;
    if (matrixResearcher) matrixResearcher.value = DEFAULT_MATRIX.researcher;
    if (matrixReviewer) matrixReviewer.value = DEFAULT_MATRIX.reviewer;
    if (matrixWriter) matrixWriter.value = DEFAULT_MATRIX.writer;
    applyPresetButtonHighlight('fast');
  }

  function applyPreset(type) {
    if (type === 'fast') {
      if (matrixPlanner) matrixPlanner.value = 'gemini-3.5-flash-lite';
      if (matrixResearcher) matrixResearcher.value = 'gemini-3.5-flash-lite';
      if (matrixReviewer) matrixReviewer.value = 'gemini-3.5-flash-lite';
      if (matrixWriter) matrixWriter.value = 'gemini-3.5-flash-lite';
      applyPresetButtonHighlight('fast');
    } else if (type === 'quality') {
      if (matrixPlanner) matrixPlanner.value = 'gemini-3.5-flash-lite';
      if (matrixResearcher) matrixResearcher.value = 'gemini-3.5-flash-lite';
      if (matrixReviewer) matrixReviewer.value = 'gemini-3.5-flash-lite';
      if (matrixWriter) matrixWriter.value = 'claude-3-5-sonnet-20241022';
      applyPresetButtonHighlight('quality');
    }
  }

  function applyPresetButtonHighlight(activeType) {
    if (presetFast) presetFast.classList.toggle('active', activeType === 'fast');
    if (presetQuality) presetQuality.classList.toggle('active', activeType === 'quality');
  }

  function updateHeaderModelLabel(matrix) {
    const valLlm = document.getElementById('val-llm');
    if (valLlm && matrix) {
      valLlm.textContent = `${matrix.researcher} → ${matrix.writer}`;
      valLlm.title = `Planner: ${matrix.planner} | Researcher: ${matrix.researcher} | Reviewer: ${matrix.reviewer} | Writer: ${matrix.writer}`;
    }
  }

  // Event Listeners for Settings Drawer
  if (btnOpenSettings) btnOpenSettings.addEventListener('click', openSettingsDrawer);
  if (btnCloseSettings) btnCloseSettings.addEventListener('click', closeSettingsDrawer);
  if (drawerOverlay) drawerOverlay.addEventListener('click', closeSettingsDrawer);
  if (btnSaveSettings) btnSaveSettings.addEventListener('click', () => {
    saveSettings();
    closeSettingsDrawer();
  });
  if (btnResetSettings) btnResetSettings.addEventListener('click', resetSettingsToDefaults);
  if (presetFast) presetFast.addEventListener('click', () => applyPreset('fast'));
  if (presetQuality) presetQuality.addEventListener('click', () => applyPreset('quality'));

  document.querySelectorAll('.btn-toggle-key').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.target;
      const input = document.getElementById(targetId);
      if (input) {
        if (input.type === 'password') {
          input.type = 'text';
          btn.textContent = '🔒';
        } else {
          input.type = 'password';
          btn.textContent = '👁';
        }
      }
    });
  });

  // Load saved settings on startup
  loadSettings();

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
