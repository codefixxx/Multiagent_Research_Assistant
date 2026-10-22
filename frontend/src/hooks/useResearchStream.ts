import { useState, useEffect, useRef, useCallback } from 'react';
import type { 
  JobStatus, 
  ResearchJobData, 
  SubQuestionItem, 
  StreamLogEntry, 
  RunCostSummary, 
  RAGScore, 
  TraceSpan,
  ModelMatrix,
  ApiKeys,
  ResearchPlan
} from '../types';

export function useResearchStream() {
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<JobStatus>('idle');
  const [jobData, setJobData] = useState<ResearchJobData | null>(null);
  const [logs, setLogs] = useState<StreamLogEntry[]>([]);
  const [subQuestions, setSubQuestions] = useState<SubQuestionItem[]>([]);
  const [activeSpans, setActiveSpans] = useState<TraceSpan[]>([]);
  const [isDispatching, setIsDispatching] = useState<boolean>(false);
  
  // Node states for the pipeline
  const [plannerState, setPlannerState] = useState<'waiting' | 'active' | 'completed'>('waiting');
  const [consolidatorState, setConsolidatorState] = useState<'waiting' | 'active' | 'completed'>('waiting');
  const [writerState, setWriterState] = useState<'waiting' | 'active' | 'completed'>('waiting');

  // Stats
  const [findingsCount, setFindingsCount] = useState<number>(0);
  const [citationsCount, setCitationsCount] = useState<number>(0);
  const [superstepsCount, setSuperstepsCount] = useState<number>(0);

  // Observability & Cost
  const [costSummary, setCostSummary] = useState<RunCostSummary | null>(null);
  const [ragScore, setRagScore] = useState<RAGScore | null>(null);

  // Timer
  const [elapsedMs, setElapsedMs] = useState<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const appendLog = useCallback((source: string, message: string, type: StreamLogEntry['type'] = 'system') => {
    const now = new Date();
    const timeStr = `${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}.${String(Math.floor(now.getMilliseconds() / 100))}`;
    setLogs(prev => [
      ...prev,
      {
        id: Math.random().toString(36).substring(2, 9),
        timestamp: timeStr,
        source,
        message,
        type
      }
    ]);
  }, []);

  const startTimer = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    startTimeRef.current = Date.now();
    setElapsedMs(0);
    timerRef.current = setInterval(() => {
      if (startTimeRef.current) {
        setElapsedMs(Date.now() - startTimeRef.current);
      }
    }, 100);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const loadTrace = useCallback(async (runId: string) => {
    try {
      const res = await fetch(`/research/${runId}/trace`);
      if (res.ok) {
        const data = await res.json();
        if (data.spans && Array.isArray(data.spans)) {
          setActiveSpans(data.spans);
        }
        if (data.cost_summary) {
          setCostSummary(data.cost_summary);
        }
        if (data.rag_score) {
          setRagScore(data.rag_score);
        }
      }
    } catch (e) {
      console.warn('Failed loading trace data:', e);
    }
  }, []);

  const finalizeRun = useCallback((finalJob: ResearchJobData) => {
    stopTimer();
    setJobData(finalJob);
    setStatus(finalJob.status);
    setPlannerState('completed');
    setConsolidatorState('completed');
    setWriterState('completed');
    setSubQuestions(prev => prev.map(w => ({ ...w, status: 'completed' })));
    setIsDispatching(false);

    if (finalJob.cost_summary) setCostSummary(finalJob.cost_summary);
    if (finalJob.rag_score) setRagScore(finalJob.rag_score);
    if (finalJob.findings_count) setFindingsCount(finalJob.findings_count);
    if (finalJob.citations_count) setCitationsCount(finalJob.citations_count);

    if (finalJob.run_id) {
      loadTrace(finalJob.run_id);
    }
  }, [stopTimer, loadTrace]);

  const handleStreamEvent = useCallback((event: MessageEvent, explicitType?: string) => {
    try {
      const data = JSON.parse(event.data);
      const evtName = explicitType || data.event || 'stream';
      const payload = data.payload || data || {};

      setSuperstepsCount(prev => prev + 1);

      switch (evtName) {
        case 'job_started':
          setStatus('planning');
          setPlannerState('active');
          appendLog('SYSTEM', payload.message || 'Investigation started', 'system');
          break;

        case 'node_start':
          if (payload.node === 'planner') setPlannerState('active');
          if (payload.node === 'consolidator') {
            setSubQuestions(prev => prev.map(w => ({ ...w, status: 'completed' })));
            setConsolidatorState('active');
          }
          if (payload.node === 'writer') setWriterState('active');
          appendLog(payload.node?.toUpperCase() || 'NODE', 'Step initiated', 'system');
          break;

        case 'node_complete':
          if (payload.node === 'planner') setPlannerState('completed');
          if (payload.node === 'consolidator') setConsolidatorState('completed');
          if (payload.node === 'writer') setWriterState('completed');
          break;

        case 'awaiting_plan_approval': {
          setStatus('awaiting_approval');
          setPlannerState('active');
          setConsolidatorState('waiting');
          setWriterState('waiting');
          const plan = payload.plan;
          if (plan) {
            setJobData(prev => ({
              ...(prev || { run_id: currentRunId || '', query: '', status: 'awaiting_approval' }),
              status: 'awaiting_approval',
              plan: plan,
              hitl_enabled: true
            }));
            const subqs = plan.sub_questions || [];
            if (subqs.length > 0) {
              setSubQuestions(subqs.map((q: any, idx: number) => ({
                id: typeof q === 'string' ? `worker_${idx + 1}` : (q.id || `subq_${idx + 1}`),
                text: typeof q === 'string' ? q : (q.sub_question || q.question || 'Sub-question investigation'),
                status: 'waiting',
                findingsCount: 0,
              })));
            }
          }
          appendLog('PLANNER', '🎯 Research plan formulated — Awaiting your review & steering decision', 'planner');
          break;
        }

        case 'planner_completed':
        case 'plan_created': {
          const isAwaiting = payload.status === 'awaiting_approval';
          setPlannerState(isAwaiting ? 'active' : 'completed');
          setConsolidatorState('waiting');
          if (isAwaiting) {
            setStatus('awaiting_approval');
            if (payload.plan) {
              setJobData(prev => ({
                ...(prev || { run_id: currentRunId || '', query: '', status: 'awaiting_approval' }),
                status: 'awaiting_approval',
                plan: payload.plan,
                hitl_enabled: true
              }));
            }
          } else {
            setStatus('researching');
          }
          const subqs = payload.sub_questions || (payload.plan && payload.plan.sub_questions) || [];
          if (subqs.length > 0) {
            setSubQuestions(subqs.map((q: any, idx: number) => ({
              id: typeof q === 'string' ? `worker_${idx + 1}` : (q.id || `subq_${idx + 1}`),
              text: typeof q === 'string' ? q : (q.sub_question || q.question || 'Sub-question investigation'),
              status: isAwaiting ? 'waiting' : 'active',
              findingsCount: 0,
            })));
          }
          appendLog('PLANNER', `Formulated ${subqs.length} parallel research streams`, 'planner');
          break;
        }

        case 'plan_approved': {
          setStatus('researching');
          setPlannerState('completed');
          setConsolidatorState('waiting');
          setWriterState('waiting');
          const plan = payload.plan;
          const subqs = payload.sub_questions || (plan && plan.sub_questions) || [];
          if (subqs.length > 0) {
            setSubQuestions(subqs.map((q: any, idx: number) => ({
              id: typeof q === 'string' ? `worker_${idx + 1}` : (q.id || `subq_${idx + 1}`),
              text: typeof q === 'string' ? q : (q.sub_question || q.question || 'Sub-question investigation'),
              status: 'active',
              findingsCount: 0,
            })));
          } else {
            setSubQuestions(prev => prev.map(w => ({ ...w, status: 'active' })));
          }
          appendLog('PLANNER', 'Plan approved. Initiating parallel web research streams.', 'planner');
          break;
        }

        case 'job_cancelled': {
          setStatus('cancelled');
          setIsDispatching(false);
          stopTimer();
          setConsolidatorState('waiting');
          setWriterState('waiting');
          setSubQuestions(prev => prev.map(w => ({ ...w, status: 'waiting' })));
          setJobData(prev => ({
            ...(prev || { run_id: currentRunId || '', query: '', status: 'cancelled' }),
            status: 'cancelled',
            report: null,
            rag_score: null,
            error_message: null,
          }));
          appendLog('SYSTEM', 'Investigation cancelled by user', 'system');
          break;
        }

        case 'researching_subquestion':
        case 'finding_extracted': {
          const subqId = payload.sub_question_id;
          if (subqId) {
            setSubQuestions(prev => prev.map(w => w.id === subqId ? {
              ...w,
              status: 'active',
              findingsCount: w.findingsCount + 1
            } : w));
          }
          if (payload.total_findings_count) {
            setFindingsCount(payload.total_findings_count);
          } else {
            setFindingsCount(prev => prev + 1);
          }
          appendLog('RESEARCHER', `Extracted evidence findings${subqId ? ' (' + subqId + ')' : ''}`, 'researcher');
          break;
        }

        case 'subquestion_reviewed':
        case 'review_complete': {
          const isRevision = Boolean(payload.is_revision);
          const approved = payload.is_revision !== undefined ? !payload.is_revision : Boolean(payload.is_approved);
          const subqId = payload.sub_question_id;
          if (subqId) {
            setSubQuestions(prev => prev.map(w => w.id === subqId ? {
              ...w,
              status: approved ? 'completed' : 'revision',
              isRevision
            } : w));
          }
          appendLog('REVIEWER', `Quality evaluation for ${subqId || 'evidence'}: ${isRevision ? 'Revision required (tightening citations)' : 'Approved'}`, 'reviewer');
          break;
        }

        case 'consolidator_completed':
          setSubQuestions(prev => prev.map(w => ({ ...w, status: 'completed' })));
          setConsolidatorState('completed');
          setWriterState('active');
          setStatus('writing');
          if (payload.total_findings_count) setFindingsCount(payload.total_findings_count);
          appendLog('CONSOLIDATOR', `Aggregated ${payload.total_findings_count || 0} findings into consolidated evidence set`, 'consolidator');
          break;

        case 'writing_completed':
        case 'report_synthesized':
          setWriterState('completed');
          if (payload.citations_count) setCitationsCount(payload.citations_count);
          appendLog('WRITER', `Synthesized technical dossier with ${payload.citations_count || 0} verified citations`, 'writer');
          break;

        case 'job_completed':
        case 'budget_exceeded':
          if (payload.cost_summary) setCostSummary(payload.cost_summary);
          if (payload.rag_score) setRagScore(payload.rag_score);
          if (payload.report) {
            setJobData(prev => ({
              ...(prev || { run_id: currentRunId || '', query: '', status: 'completed' }),
              report: payload.report,
              status: evtName === 'budget_exceeded' ? 'budget_exceeded' : 'completed',
              cost_summary: payload.cost_summary,
              rag_score: payload.rag_score
            }));
          }
          finalizeRun({
            run_id: currentRunId || '',
            status: evtName === 'budget_exceeded' ? 'budget_exceeded' : 'completed',
            query: '',
            report: payload.report,
            cost_summary: payload.cost_summary,
            rag_score: payload.rag_score
          });
          appendLog('SYSTEM', evtName === 'budget_exceeded' ? 'Run concluded: Budget threshold reached' : 'Investigation successfully concluded', 'system');
          break;

        case 'job_failed':
          setStatus('failed');
          setIsDispatching(false);
          stopTimer();
          setJobData(prev => ({
            run_id: currentRunId || (prev?.run_id ?? ''),
            status: 'failed',
            query: prev?.query ?? '',
            report: null,
            error_message: payload.error || payload.error_message || 'Execution encountered an error',
            error_code: payload.code || payload.error_code,
            error_suggestion: payload.suggestion || payload.error_suggestion,
            error_details: payload.details || payload.error_details,
          }));
          appendLog('SYSTEM', `Run failed: ${payload.error || payload.error_message || 'Execution encountered an error'}`, 'error');
          if (payload.suggestion) {
            appendLog('SYSTEM', `💡 Actionable fix: ${payload.suggestion}`, 'system');
          }
          break;
      }
    } catch (e) {
      console.warn('Failed parsing SSE packet:', e);
    }
  }, [currentRunId, appendLog, finalizeRun, stopTimer]);

  const connectSSE = useCallback((runId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    try {
      const es = new EventSource(`/research/${runId}/stream`);
      eventSourceRef.current = es;

      const namedEvents = [
        'job_started',
        'awaiting_plan_approval',
        'plan_approved',
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
        'job_cancelled',
        'budget_exceeded',
        'job_failed',
        'node_start',
        'node_complete'
      ];

      es.onmessage = (evt) => handleStreamEvent(evt);
      namedEvents.forEach(name => {
        es.addEventListener(name, (evt) => handleStreamEvent(evt, name));
      });

      es.onerror = () => {
        // Fallback polling will maintain sync
        if (es.readyState === EventSource.CLOSED) {
          es.close();
        }
      };
    } catch (e) {
      console.warn('Failed initializing EventSource:', e);
    }
  }, [handleStreamEvent]);

  const startPolling = useCallback((runId: string) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

    pollIntervalRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/research/${runId}`);
        if (!res.ok) return;
        const data: ResearchJobData = await res.json();
        
        if (data.status === 'failed') {
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          if (eventSourceRef.current) eventSourceRef.current.close();
          setStatus('failed');
          setIsDispatching(false);
          stopTimer();
          setJobData(data);
          if (data.error_message) {
            appendLog('SYSTEM', `Run failed: ${data.error_message}`, 'error');
          }
          if (data.error_suggestion) {
            appendLog('SYSTEM', `💡 Actionable fix: ${data.error_suggestion}`, 'system');
          }
        } else if (data.status === 'cancelled') {
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
          if (eventSourceRef.current) eventSourceRef.current.close();
          setStatus('cancelled');
          setIsDispatching(false);
          stopTimer();
          setJobData(data);
          setConsolidatorState('waiting');
          setWriterState('waiting');
          setSubQuestions(prev => prev.map(w => ({ ...w, status: 'waiting' })));
          appendLog('SYSTEM', 'Investigation cancelled by user', 'system');
        } else if (data.status === 'completed' || data.status === 'budget_exceeded') {
          if (data.report && (data.report.title || data.report.markdown_output)) {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            if (eventSourceRef.current) eventSourceRef.current.close();
            finalizeRun(data);
          }
        } else if (data.status === 'awaiting_approval') {
          setStatus('awaiting_approval');
          setPlannerState('active');
          setConsolidatorState('waiting');
          setWriterState('waiting');
          setJobData(data);
        } else {
          // Reconcile in-progress status
          setStatus(data.status);
          if (data.findings_count) setFindingsCount(data.findings_count);
          if (data.citations_count) setCitationsCount(data.citations_count);
        }
      } catch (e) {
        console.warn('Polling error:', e);
      }
    }, 2500);
  }, [finalizeRun, stopTimer, appendLog]);

  const dispatchInvestigation = useCallback(async (
    query: string,
    subQuestionsCount: number = 2,
    timeLimitSec: number = 120,
    deepScrape: boolean = true,
    modelMatrix?: ModelMatrix,
    apiKeys?: ApiKeys,
    focusMode: string = 'general',
    hitlEnabled: boolean = false
  ) => {
    // Reset workspace
    setJobData(null);
    setLogs([]);
    setSubQuestions([]);
    setActiveSpans([]);
    setFindingsCount(0);
    setCitationsCount(0);
    setSuperstepsCount(0);
    setCostSummary(null);
    setRagScore(null);
    setPlannerState('waiting');
    setConsolidatorState('waiting');
    setWriterState('waiting');
    setIsDispatching(true);
    setStatus('pending');

    startTimer();
    const modeLabel = focusMode === 'general' ? '' : ` [${focusMode.toUpperCase()}]`;
    const hitlLabel = hitlEnabled ? ' (HITL Plan Review enabled)' : '';
    appendLog('SYSTEM', `Dispatching${modeLabel} investigation: "${query}"${hitlLabel}`, 'system');

    try {
      const payload = {
        query,
        max_sub_questions: subQuestionsCount,
        max_wall_clock_seconds: timeLimitSec,
        deep_scrape: deepScrape,
        focus_mode: focusMode,
        hitl_enabled: hitlEnabled,
        model_matrix: modelMatrix,
        api_keys: apiKeys
      };

      const res = await fetch('/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        let errMsg = errJson.error || errJson.message || '';
        if (!errMsg && errJson.detail) {
          if (Array.isArray(errJson.detail)) {
            errMsg = errJson.detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ');
          } else {
            errMsg = String(errJson.detail);
          }
        }
        if (!errMsg) {
          errMsg = `Server returned HTTP ${res.status}`;
        }
        const suggestion = errJson.suggestion || '';
        const code = errJson.code || `HTTP_${res.status}`;
        setJobData({
          run_id: '',
          query,
          status: 'failed',
          error_message: errMsg,
          error_code: code,
          error_suggestion: suggestion,
          error_details: errJson.details,
        });
        throw new Error(`${errMsg}${suggestion ? ` (💡 ${suggestion})` : ''}`);
      }

      const data = await res.json();
      const runId = data.run_id;
      setCurrentRunId(runId);
      
      try {
        localStorage.setItem('multiagent_last_run_id', runId);
        window.history.replaceState({}, '', '?run_id=' + runId);
      } catch {}

      appendLog('SYSTEM', `Job accepted [ID: ${runId.slice(0, 8)}]`, 'system');
      connectSSE(runId);
      startPolling(runId);

    } catch (err: any) {
      appendLog('SYSTEM', `Failed to dispatch: ${err.message}`, 'error');
      setStatus('failed');
      setIsDispatching(false);
      stopTimer();
    }
  }, [startTimer, stopTimer, appendLog, connectSSE, startPolling]);

  const steerPlan = useCallback(async (
    action: 'approve' | 'modify' | 'regenerate' | 'reject',
    modifiedPlan?: ResearchPlan,
    feedback?: string
  ) => {
    if (!currentRunId) return false;
    try {
      appendLog('USER', `Plan steering decision: ${action.toUpperCase()}${feedback ? ` ("${feedback}")` : ''}`, 'system');
      if (action === 'approve' || action === 'modify') {
        setStatus('researching');
        setPlannerState('completed');
        setConsolidatorState('waiting');
        setWriterState('waiting');
        if (modifiedPlan && modifiedPlan.sub_questions && modifiedPlan.sub_questions.length > 0) {
          setSubQuestions(modifiedPlan.sub_questions.map((q, idx) => ({
            id: q.id || `subq_${idx + 1}`,
            text: q.question,
            status: 'active',
            findingsCount: 0,
          })));
          setJobData(prev => prev ? { ...prev, plan: modifiedPlan, status: 'researching' } : null);
        } else {
          setSubQuestions(prev => prev.map(w => ({ ...w, status: 'active' })));
        }
      } else if (action === 'regenerate') {
        setStatus('planning');
        setPlannerState('active');
        setConsolidatorState('waiting');
        setWriterState('waiting');
        setSubQuestions([]);
        appendLog('PLANNER', 'Re-planning with user constraints...', 'planner');
      } else if (action === 'reject') {
        setStatus('cancelled');
        setIsDispatching(false);
        stopTimer();
        setJobData(prev => ({
          ...(prev || { run_id: currentRunId || '', query: '', status: 'cancelled' }),
          status: 'cancelled',
          report: null,
          rag_score: null,
          error_message: null
        }));
        setConsolidatorState('waiting');
        setWriterState('waiting');
        setSubQuestions(prev => prev.map(w => ({ ...w, status: 'waiting' })));
        appendLog('SYSTEM', 'Investigation cancelled by user', 'system');
      }

      const res = await fetch(`/research/${currentRunId}/steer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          modified_plan: modifiedPlan,
          feedback
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        appendLog('SYSTEM', `Steering failed: ${err.detail || res.statusText}`, 'error');
        return false;
      }
      return true;
    } catch (e: any) {
      appendLog('SYSTEM', `Steering error: ${e.message}`, 'error');
      return false;
    }
  }, [currentRunId, appendLog, stopTimer]);

  const loadRun = useCallback(async (runId: string) => {
    try {
      if (eventSourceRef.current) eventSourceRef.current.close();
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      stopTimer();

      setCurrentRunId(runId);
      try {
        localStorage.setItem('multiagent_last_run_id', runId);
        window.history.replaceState({}, '', '?run_id=' + runId);
      } catch {}

      // Cleanly reset previous run transient state to prevent bleed across runs
      setLogs([]);
      setActiveSpans([]);
      setJobData(null);
      setSubQuestions([]);
      setFindingsCount(0);
      setCitationsCount(0);
      setCostSummary(null);
      setRagScore(null);
      setPlannerState('waiting');
      setConsolidatorState('waiting');
      setWriterState('waiting');

      const res = await fetch(`/research/${runId}`);
      if (!res.ok) return;
      const data: ResearchJobData = await res.json();
      if (data && data.run_id) {
        setJobData(data);
        setStatus(data.status);
        setFindingsCount(data.findings_count || 0);
        setCitationsCount(data.citations_count || 0);
        setCostSummary(data.cost_summary || null);
        setRagScore(data.rag_score || null);

        // Map sub-questions from plan if available
        if (data.plan?.sub_questions && Array.isArray(data.plan.sub_questions)) {
          const isDone = data.status === 'completed' || data.status === 'budget_exceeded' || data.status === 'writing';
          const isCancelled = data.status === 'cancelled';
          const isAwaiting = data.status === 'awaiting_approval';
          setSubQuestions(data.plan.sub_questions.map((q, idx) => ({
            id: q.id || `subq_${idx + 1}`,
            text: q.question,
            status: isDone ? 'completed' : isCancelled ? 'waiting' : isAwaiting ? 'waiting' : 'active',
            findingsCount: 0
          })));
        }

        if (data.status === 'completed' || data.status === 'budget_exceeded') {
          setPlannerState('completed');
          setConsolidatorState('completed');
          setWriterState('completed');
          loadTrace(runId);
        } else if (data.status === 'writing') {
          setPlannerState('completed');
          setConsolidatorState('completed');
          setWriterState('active');
          connectSSE(runId);
          startPolling(runId);
          startTimer();
        } else if (data.status === 'researching') {
          setPlannerState('completed');
          setConsolidatorState('waiting');
          setWriterState('waiting');
          connectSSE(runId);
          startPolling(runId);
          startTimer();
        } else if (data.status === 'awaiting_approval') {
          setPlannerState('active');
          setConsolidatorState('waiting');
          setWriterState('waiting');
          loadTrace(runId);
        } else if (data.status === 'planning' || data.status === 'queued') {
          setPlannerState('active');
          setConsolidatorState('waiting');
          setWriterState('waiting');
          connectSSE(runId);
          startPolling(runId);
          startTimer();
        } else if (data.status === 'cancelled') {
          setPlannerState('completed');
          setConsolidatorState('waiting');
          setWriterState('waiting');
          loadTrace(runId);
        } else if (data.status === 'failed') {
          setPlannerState('waiting');
          setConsolidatorState('waiting');
          setWriterState('waiting');
          loadTrace(runId);
        }
      }
    } catch (e) {
      console.warn('Failed loading run:', e);
    }
  }, [connectSSE, startPolling, startTimer, stopTimer, loadTrace]);

  // Load existing run on mount if URL has ?run_id=
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const runIdFromUrl = params.get('run_id') || localStorage.getItem('multiagent_last_run_id');

    if (runIdFromUrl) {
      loadRun(runIdFromUrl);
    }

    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [loadRun]);

  const formattedTimer = (() => {
    const totalSec = Math.floor(elapsedMs / 1000);
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    const tenths = Math.floor((elapsedMs % 1000) / 100);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${tenths}`;
  })();

  return {
    currentRunId,
    status,
    jobData,
    logs,
    subQuestions,
    activeSpans,
    isDispatching,
    plannerState,
    consolidatorState,
    writerState,
    findingsCount,
    citationsCount,
    superstepsCount,
    costSummary,
    ragScore,
    formattedTimer,
    dispatchInvestigation,
    steerPlan,
    loadRun,
    loadTrace
  };
}

