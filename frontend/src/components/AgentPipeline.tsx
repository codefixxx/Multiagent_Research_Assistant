import type { SubQuestionItem, JobStatus } from '../types';
import { CheckCircle2, Loader2, Clock, XCircle } from 'lucide-react';

interface AgentPipelineProps {
  plannerState: 'waiting' | 'active' | 'completed';
  consolidatorState: 'waiting' | 'active' | 'completed';
  writerState: 'waiting' | 'active' | 'completed';
  workers: SubQuestionItem[];
  isAwaitingApproval?: boolean;
  status?: JobStatus;
}

export const AgentPipeline: React.FC<AgentPipelineProps> = ({
  plannerState,
  consolidatorState,
  writerState,
  workers,
  isAwaitingApproval = false,
  status = 'idle'
}) => {
  const isAwaiting = isAwaitingApproval || status === 'awaiting_approval';
  const isCancelled = status === 'cancelled';
  const isDoneAll = status === 'completed' || status === 'budget_exceeded';
  const isFailed = status === 'failed';

  // Planning is only active while formulating the initial plan
  const isPlanningActive = !isCancelled && !isFailed && !isAwaiting && (
    (status === 'planning' || status === 'queued' || status === 'pending') &&
    plannerState !== 'completed'
  );
  const isPlanningDone = !isCancelled && (
    isAwaiting ||
    plannerState === 'completed' ||
    status === 'researching' ||
    status === 'writing' ||
    isDoneAll
  );

  // Web research can NEVER be active while waiting for plan approval, while still planning, or if cancelled/failed
  const isResearchActive = !isCancelled && !isFailed && !isAwaiting && !isPlanningActive && (
    status === 'researching' ||
    workers.some(w => w.status === 'active' || w.status === 'revision')
  );
  const isResearchDone = !isCancelled && !isAwaiting && !isPlanningActive && (
    (workers.length > 0 && workers.every(w => w.status === 'completed')) ||
    consolidatorState === 'active' ||
    consolidatorState === 'completed' ||
    writerState === 'active' ||
    writerState === 'completed' ||
    status === 'writing' ||
    isDoneAll
  );

  const isConsolidatorActive = !isCancelled && !isFailed && !isAwaiting && consolidatorState === 'active';
  const isConsolidatorDone = !isCancelled && !isAwaiting && (
    consolidatorState === 'completed' ||
    writerState === 'active' ||
    writerState === 'completed' ||
    status === 'writing' ||
    isDoneAll
  );

  const isWriterActive = !isCancelled && !isFailed && !isAwaiting && writerState === 'active';
  const isWriterDone = !isCancelled && !isAwaiting && (writerState === 'completed' || isDoneAll);

  // Determine which step encountered the terminal error
  const failedStepIndex = isFailed
    ? !isPlanningDone
      ? 1
      : !isResearchDone
      ? 2
      : !isConsolidatorDone
      ? 3
      : 4
    : -1;

  const steps = [
    {
      num: '1',
      title: 'Planning',
      desc: isCancelled
        ? 'Planning phase completed'
        : failedStepIndex === 1
        ? 'Failed during strategy formulation'
        : isAwaiting
        ? 'Plan formulated — awaiting review'
        : isPlanningDone
        ? 'Research strategy formulated'
        : 'Formulating search strategy',
      state: isCancelled
        ? 'cancelled'
        : failedStepIndex === 1
        ? 'failed'
        : isAwaiting
        ? 'awaiting'
        : isPlanningActive
        ? 'active'
        : isPlanningDone
        ? 'completed'
        : 'waiting',
    },
    {
      num: '2',
      title: 'Searching Web',
      desc: isCancelled
        ? 'Cancelled before retrieval'
        : failedStepIndex === 2
        ? workers.length > 0
          ? `Halted during inquiry (${workers.length} topics)`
          : 'Halted during web inquiry'
        : failedStepIndex === 1
        ? 'Halted before web retrieval'
        : isAwaiting
        ? 'Awaiting plan approval'
        : workers.length > 0
        ? `${workers.length} parallel inquiries`
        : isResearchDone
        ? 'Web evidence gathered'
        : 'Gathering web sources',
      state: isCancelled
        ? 'cancelled'
        : failedStepIndex === 2
        ? 'failed'
        : isAwaiting || isPlanningActive || failedStepIndex === 1
        ? 'waiting'
        : isResearchActive
        ? 'active'
        : isResearchDone
        ? 'completed'
        : 'waiting',
    },
    {
      num: '3',
      title: 'Verifying Facts',
      desc: isCancelled
        ? 'Cancelled before verification'
        : failedStepIndex === 3
        ? 'Failed during verification'
        : failedStepIndex > 0 && failedStepIndex < 3
        ? 'Halted before verification'
        : 'Cross-checking source claims',
      state: isCancelled
        ? 'cancelled'
        : failedStepIndex === 3
        ? 'failed'
        : failedStepIndex > 0 && failedStepIndex < 3
        ? 'waiting'
        : isAwaiting || isPlanningActive || (isResearchActive && !isResearchDone)
        ? 'waiting'
        : isConsolidatorActive
        ? 'active'
        : isConsolidatorDone
        ? 'completed'
        : 'waiting',
    },
    {
      num: '4',
      title: 'Writing Report',
      desc: isCancelled
        ? 'Cancelled before synthesis'
        : failedStepIndex === 4
        ? 'Failed during synthesis'
        : failedStepIndex > 0 && failedStepIndex < 4
        ? 'Halted before synthesis'
        : 'Synthesizing final document',
      state: isCancelled
        ? 'cancelled'
        : failedStepIndex === 4
        ? 'failed'
        : failedStepIndex > 0 && failedStepIndex < 4
        ? 'waiting'
        : isAwaiting || isPlanningActive || !isResearchDone || isConsolidatorActive
        ? 'waiting'
        : isWriterActive
        ? 'active'
        : isWriterDone
        ? 'completed'
        : 'waiting',
    },
  ];

  return (
    <section className="w-full max-w-[1600px] mx-auto px-6 md:px-10 py-3">
      <div className="bg-[#131217] border border-[#222224] rounded-md p-4 sm:p-5">
        {/* Stepper Header */}
        <div className="flex items-center justify-between text-xs text-[#8a8c92] pb-3 mb-3 border-b border-[#1b1a1f]">
          <span className="font-medium text-white text-xs">
            Research progress
          </span>
          <span className="text-[#8a8c92] text-xs">
            {isCancelled
              ? '⛔ Investigation cancelled by user'
              : isFailed
              ? '⚠️ Investigation halted due to execution error'
              : isAwaiting
              ? '🎯 Plan formulated — review & steering required to proceed'
              : writerState === 'completed'
              ? 'Research complete'
              : writerState === 'active'
              ? 'Drafting final answer...'
              : consolidatorState === 'active'
              ? 'Cross-referencing sources...'
              : isResearchActive
              ? 'Gathering web evidence...'
              : isPlanningActive
              ? 'Analyzing question...'
              : 'Ready for question'}
          </span>
        </div>

        {/* 4-Step Stepper Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
          {steps.map((step) => {
            const isStepAwaiting = step.state === 'awaiting';
            const isStepCancelled = step.state === 'cancelled';
            const isStepFailed = step.state === 'failed';
            const isActive = step.state === 'active';
            const isCompleted = step.state === 'completed';

            return (
              <div
                key={step.num}
                className={`p-3.5 rounded-md border transition-colors ${
                  isStepFailed
                    ? 'bg-[#171719] border-[#e5566f]/40 border-b-2'
                    : isStepAwaiting
                    ? 'bg-[#171719] border-[#d9a441] border-b-2'
                    : isStepCancelled
                    ? 'bg-[#171719] border-[#1b1a1f] opacity-60'
                    : isActive
                    ? 'bg-[#171719] border-[#4a8ad6] border-b-2'
                    : isCompleted
                    ? 'bg-[#171719] border-[#222224]'
                    : 'bg-[#171719] border-[#1b1a1f]'
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs text-[#8a8c92] tabular">
                    Step {step.num}
                  </span>
                  {isStepFailed ? (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#3b181e] text-[#e5566f] border border-[#e5566f]/30">
                      <XCircle className="w-3 h-3 text-[#e5566f]" />
                      <span>Failed</span>
                    </span>
                  ) : isStepAwaiting ? (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#d9a441]/20 text-[#d9a441] border border-[#d9a441]/30">
                      <span>Reviewing Plan</span>
                    </span>
                  ) : isStepCancelled ? (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs text-[#8a8c92]/60 bg-[#212023]/60">
                      <XCircle className="w-3 h-3 text-[#e5566f]/70" />
                      <span>Cancelled</span>
                    </span>
                  ) : isActive ? (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#1c2738] text-[#4a8ad6]">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span>Working</span>
                    </span>
                  ) : isCompleted ? (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#1b2828] text-[#5fc39c]">
                      <CheckCircle2 className="w-3 h-3" />
                      <span>Done</span>
                    </span>
                  ) : (
                    <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-xs text-[#8a8c92]/60">
                      <Clock className="w-3 h-3" />
                      <span>Waiting</span>
                    </span>
                  )}
                </div>
                <div className="font-semibold text-sm text-white">{step.title}</div>
                <div className="text-xs text-[#8a8c92] mt-1 break-words">{step.desc}</div>
              </div>
            );
          })}
        </div>

        {/* Sub-Topics when active */}
        {workers.length > 0 && (
          <div className="mt-3.5 pt-3.5 border-t border-[#1b1a1f] space-y-2">
            <div className="text-xs font-medium text-[#8a8c92]">
              Investigating key angles:
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {workers.map((worker) => (
                <div
                  key={worker.id}
                  className={`px-3.5 py-2 rounded-md bg-[#171719] border ${isFailed ? 'border-[#e5566f]/25 opacity-75' : 'border-[#222224]'} flex items-center justify-between text-xs`}
                >
                  <span className="text-white/90 truncate pr-3">{worker.text}</span>
                  <span className={`text-xs ${isFailed ? 'text-[#e5566f]/80' : 'text-[#4a8ad6]'} shrink-0 font-medium tabular`}>
                    {worker.findingsCount} facts found
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
};
