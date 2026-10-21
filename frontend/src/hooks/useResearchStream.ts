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
  ApiKeys
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
          if (payload.node === 'consolidator') setConsolidatorState('active');
          if (payload.node === 'writer') setWriterState('active');
          appendLog(payload.node?.toUpperCase() || 'NODE', 'Step initiated', 'system');
          break;

        case 'node_complete':
          if (payload.node === 'planner') setPlannerState('completed');
          if (payload.node === 'consolidator') setConsolidatorState('completed');
          if (payload.node === 'writer') setWriterState('completed');
          break;

        case 'planner_completed':
        case 'plan_created': {
          setPlannerState('completed');
          setConsolidatorState('active');
          setStatus('researching');
          const subqs = payload.sub_questions || (payload.plan && payload.plan.sub_questions) || [];
          if (subqs.length > 0) {
            setSubQuestions(subqs.map((q: any, idx: number) => ({
              id: typeof q === 'string' ? `worker_${idx + 1}` : (q.id || `subq_${idx + 1}`),
              text: typeof q === 'string' ? q : (q.sub_question || q.question || 'Sub-question investigation'),
              status: 'active',
              findingsCount: 0,
            })));
          }
          appendLog('PLANNER', `Formulated ${subqs.length} parallel research streams`, 'planner');
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
          appendLog('SYSTEM', `Run failed: ${payload.error || 'Execution encountered an error'}`, 'error');
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
        
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'budget_exceeded') {
          if (data.report && (data.report.title || data.report.markdown_output)) {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            if (eventSourceRef.current) eventSourceRef.current.close();
            finalizeRun(data);
          }
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
  }, [finalizeRun]);

  const dispatchInvestigation = useCallback(async (
    query: string,
    subQuestionsCount: number = 2,
    timeLimitSec: number = 120,
    deepScrape: boolean = true,
    modelMatrix?: ModelMatrix,
    apiKeys?: ApiKeys
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
    appendLog('SYSTEM', `Dispatching investigation: "${query}"`, 'system');

    try {
      const payload = {
        query,
        max_sub_questions: subQuestionsCount,
        max_wall_clock_seconds: timeLimitSec,
        deep_scrape: deepScrape,
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
        const errMsg = errJson.error || errJson.detail || errJson.message || `Server returned HTTP ${res.status}`;
        const suggestion = errJson.suggestion ? ` (💡 ${errJson.suggestion})` : '';
        throw new Error(`${errMsg}${suggestion}`);
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

      const res = await fetch(`/research/${runId}`);
      if (!res.ok) return;
      const data: ResearchJobData = await res.json();
      if (data && data.run_id) {
        setJobData(data);
        setStatus(data.status);
        if (data.findings_count) setFindingsCount(data.findings_count);
        if (data.citations_count) setCitationsCount(data.citations_count);
        if (data.cost_summary) setCostSummary(data.cost_summary);
        if (data.rag_score) setRagScore(data.rag_score);
        if (data.status === 'completed' || data.status === 'budget_exceeded') {
          setPlannerState('completed');
          setConsolidatorState('completed');
          setWriterState('completed');
          loadTrace(runId);
        } else if (data.status !== 'failed') {
          connectSSE(runId);
          startPolling(runId);
          startTimer();
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
    loadRun,
    loadTrace
  };
}

