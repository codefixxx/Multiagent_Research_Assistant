import { useState } from 'react';
import { useResearchStream } from './hooks/useResearchStream';
import { Header } from './components/Header';
import { CommandDeck } from './components/CommandDeck';
import { AgentPipeline } from './components/AgentPipeline';
import { SplitStudio } from './components/SplitStudio';
import { CitationPopover } from './components/CitationPopover';
import { SettingsDrawer } from './components/SettingsDrawer';
import { TraceDrawer } from './components/TraceDrawer';
import type { Citation, ModelMatrix, ApiKeys } from './types';

export function App() {
  const {
    currentRunId,
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
  } = useResearchStream();

  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isTraceOpen, setIsTraceOpen] = useState(false);

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

  const handleDispatch = (
    query: string,
    subQuestionsCount: number,
    timeLimitSec: number,
    deepScrape: boolean
  ) => {
    dispatchInvestigation(
      query,
      subQuestionsCount,
      timeLimitSec,
      deepScrape,
      activeModelMatrix,
      activeApiKeys
    );
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
      />

      {/* 2. Main Workspace */}
      <div className="flex-1 flex flex-col pb-12">
        {/* Command Bar */}
        <CommandDeck
          isDispatching={isDispatching}
          onDispatch={handleDispatch}
        />

        {/* Dynamic Topology Stepper */}
        <AgentPipeline
          plannerState={plannerState}
          consolidatorState={consolidatorState}
          writerState={writerState}
          workers={subQuestions}
        />

        {/* Dual Canvas Studio */}
        <SplitStudio
          jobData={jobData}
          logs={logs}
          ragScore={ragScore}
          findingsCount={findingsCount}
          citationsCount={citationsCount}
          superstepsCount={superstepsCount}
          spans={activeSpans}
          onSelectCitation={(citation) => setSelectedCitation(citation)}
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
      />

      <TraceDrawer
        isOpen={isTraceOpen}
        onClose={() => setIsTraceOpen(false)}
        runId={currentRunId}
        spans={activeSpans}
        costSummary={costSummary}
        ragScore={ragScore}
      />
    </div>
  );
}

export default App;
