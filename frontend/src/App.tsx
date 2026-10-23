import { useState, useEffect } from 'react';
import { useResearchStream } from './hooks/useResearchStream';
import { Header } from './components/Header';
import { CommandDeck } from './components/CommandDeck';
import { AgentPipeline } from './components/AgentPipeline';
import { SplitStudio } from './components/SplitStudio';
import { CitationPopover } from './components/CitationPopover';
import { SettingsDrawer } from './components/SettingsDrawer';
import { TraceDrawer } from './components/TraceDrawer';
import { HistoryDrawer } from './components/HistoryDrawer';
import type { Citation, ModelMatrix, ApiKeys } from './types';

export function App() {
  const {
    currentRunId,
    jobData,
    logs,
    subQuestions,
    activeSpans,
    status,
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
  } = useResearchStream();

  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isTraceOpen, setIsTraceOpen] = useState(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [requireByok, setRequireByok] = useState(false);

  useEffect(() => {
    fetch('/health')
      .then(res => res.json())
      .then(data => {
        if (data && data.require_byok) {
          setRequireByok(true);
        }
      })
      .catch(() => {});
  }, []);

  const [activeModelMatrix, setActiveModelMatrix] = useState<ModelMatrix | undefined>(() => {
    try {
      const saved = localStorage.getItem('multiagent_model_matrix');
      return saved ? JSON.parse(saved) : undefined;
    } catch {
      return undefined;
    }
  });

  const [activeApiKeys, setActiveApiKeys] = useState<ApiKeys | undefined>(() => {
    try {
      const saved = localStorage.getItem('multiagent_byok_keys');
      return saved ? JSON.parse(saved) : undefined;
    } catch {
      return undefined;
    }
  });

  // Centralized research settings state shared between CommandDeck and retry/regenerate workflows
  const [query, setQuery] = useState('');
  const [depth, setDepth] = useState<number>(() => {
    try {
      const saved = localStorage.getItem('multiagent_depth');
      return saved ? Number(saved) : 2;
    } catch {
      return 2;
    }
  });
  const [timeLimit, setTimeLimit] = useState<number>(() => {
    try {
      const saved = localStorage.getItem('multiagent_time_limit');
      return saved ? Number(saved) : 120;
    } catch {
      return 120;
    }
  });
  const [deepScrape, setDeepScrape] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem('multiagent_deep_scrape');
      return saved !== null ? saved === 'true' : true;
    } catch {
      return true;
    }
  });
  const [focusMode, setFocusMode] = useState<string>(() => {
    try {
      return localStorage.getItem('multiagent_focus_mode') || 'general';
    } catch {
      return 'general';
    }
  });
  const [hitlEnabled, setHitlEnabled] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem('multiagent_hitl_enabled');
      return saved !== null ? saved === 'true' : true;
    } catch {
      return true;
    }
  });

  const handleDepthChange = (newDepth: number) => {
    setDepth(newDepth);
    try {
      localStorage.setItem('multiagent_depth', String(newDepth));
    } catch {}
  };

  const handleTimeLimitChange = (newLimit: number) => {
    setTimeLimit(newLimit);
    try {
      localStorage.setItem('multiagent_time_limit', String(newLimit));
    } catch {}
  };

  const handleDeepScrapeChange = (checked: boolean) => {
    setDeepScrape(checked);
    try {
      localStorage.setItem('multiagent_deep_scrape', String(checked));
    } catch {}
  };

  const handleFocusModeChange = (newFocus: string) => {
    setFocusMode(newFocus);
    try {
      localStorage.setItem('multiagent_focus_mode', newFocus);
    } catch {}
  };

  const handleHitlChange = (checked: boolean) => {
    setHitlEnabled(checked);
    try {
      localStorage.setItem('multiagent_hitl_enabled', String(checked));
    } catch {}
  };

  // Sync settings when loaded from existing run or history
  useEffect(() => {
    if (jobData?.query) {
      setQuery(prev => prev || (jobData.query ?? ''));
    }
    if (jobData?.focus_mode) {
      setFocusMode(jobData.focus_mode);
    }
    if (jobData?.hitl_enabled !== undefined) {
      setHitlEnabled(jobData.hitl_enabled);
    }
  }, [jobData]);

  const handleDispatch = (
    targetQuery: string,
    subQuestionsCount: number = depth,
    timeLimitSec: number = timeLimit,
    isDeepScrape: boolean = deepScrape,
    targetFocusMode: string = focusMode,
    isHitlEnabled: boolean = hitlEnabled
  ) => {
    if (requireByok && !activeApiKeys?.gemini) {
      setIsSettingsOpen(true);
      return;
    }
    // Cleanly cancel previous paused job if re-dispatching from awaiting approval
    if (currentRunId && status === 'awaiting_approval') {
      steerPlan('reject').catch(() => {});
    }
    dispatchInvestigation(
      targetQuery,
      subQuestionsCount,
      timeLimitSec,
      isDeepScrape,
      activeModelMatrix,
      activeApiKeys,
      targetFocusMode,
      isHitlEnabled
    );
  };

  const handleRetryOrRegenerate = () => {
    const targetQuery = query.trim() || jobData?.query;
    if (targetQuery) {
      handleDispatch(
        targetQuery,
        depth,
        timeLimit,
        deepScrape,
        focusMode,
        hitlEnabled
      );
    }
  };

  const handleSaveSettings = (matrix: ModelMatrix, keys: ApiKeys) => {
    setActiveModelMatrix(matrix);
    setActiveApiKeys(keys);
  };

  const totalTokens = (costSummary?.total_prompt_tokens || 0) + (costSummary?.total_completion_tokens || 0);
  const totalCostUsd = costSummary?.total_cost_usd || 0;

  return (
    <div className="min-h-screen bg-[#171719] text-white flex flex-col">
      {/* 1. Header with System Telemetry */}
      <Header
        tokens={totalTokens}
        costUsd={totalCostUsd}
        timer={formattedTimer}
        isDispatching={isDispatching}
        hasTrace={activeSpans.length > 0}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onOpenTrace={() => setIsTraceOpen(true)}
        onOpenHistory={() => setIsHistoryOpen(true)}
      />

      {/* 2. Main Workspace */}
      <div className="flex-1 flex flex-col pb-12">
        {/* Command Bar */}
        <CommandDeck
          isDispatching={isDispatching}
          status={status}
          query={query}
          onQueryChange={setQuery}
          depth={depth}
          onDepthChange={handleDepthChange}
          timeLimit={timeLimit}
          onTimeLimitChange={handleTimeLimitChange}
          deepScrape={deepScrape}
          onDeepScrapeChange={handleDeepScrapeChange}
          focusMode={focusMode}
          onFocusModeChange={handleFocusModeChange}
          hitlEnabled={hitlEnabled}
          onHitlEnabledChange={handleHitlChange}
          onDispatch={handleDispatch}
        />

        {/* Dynamic Topology Stepper */}
        <AgentPipeline
          plannerState={plannerState}
          consolidatorState={consolidatorState}
          writerState={writerState}
          workers={subQuestions}
          isAwaitingApproval={status === 'awaiting_approval'}
          status={status}
        />

        {/* Dual Canvas Studio */}
        <SplitStudio
          jobData={jobData}
          status={status}
          logs={logs}
          ragScore={ragScore}
          findingsCount={findingsCount}
          citationsCount={citationsCount}
          superstepsCount={superstepsCount}
          spans={activeSpans}
          onSelectCitation={(citation) => setSelectedCitation(citation)}
          onOpenSettings={() => setIsSettingsOpen(true)}
          onSteerPlan={steerPlan}
          onRetry={handleRetryOrRegenerate}
        />
      </div>

      {/* 3. Modals & Drawers */}
      <CitationPopover
        citation={selectedCitation}
        onClose={() => setSelectedCitation(null)}
      />

      <SettingsDrawer
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onSave={handleSaveSettings}
        requireByok={requireByok}
      />

      <TraceDrawer
        isOpen={isTraceOpen}
        onClose={() => setIsTraceOpen(false)}
        runId={currentRunId}
        spans={activeSpans}
        costSummary={costSummary}
        ragScore={ragScore}
      />

      <HistoryDrawer
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        onSelectRun={loadRun}
        currentRunId={currentRunId}
      />
    </div>
  );
}

export default App;
