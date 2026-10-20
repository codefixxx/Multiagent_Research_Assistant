import React from 'react';
import type { SubQuestionItem } from '../types';
import { CheckCircle2, Loader2, Clock } from 'lucide-react';

interface AgentPipelineProps {
  plannerState: 'waiting' | 'active' | 'completed';
  consolidatorState: 'waiting' | 'active' | 'completed';
  writerState: 'waiting' | 'active' | 'completed';
  workers: SubQuestionItem[];
}

export const AgentPipeline: React.FC<AgentPipelineProps> = ({
  plannerState,
  consolidatorState,
  writerState,
  workers
}) => {
  const isResearching = workers.some(w => w.status === 'active' || w.status === 'revision');
  const isResearchDone = workers.length > 0 && workers.every(w => w.status === 'completed');

  const steps = [
    {
      num: '1',
      title: 'Planning',
      desc: 'Formulating search strategy',
      state: plannerState,
    },
    {
      num: '2',
      title: 'Searching Web',
      desc: workers.length > 0 ? `${workers.length} parallel inquiries` : 'Gathering web sources',
      state: isResearching ? 'active' : isResearchDone ? 'completed' : 'waiting',
    },
    {
      num: '3',
      title: 'Verifying Facts',
      desc: 'Cross-checking source claims',
      state: consolidatorState,
    },
    {
      num: '4',
      title: 'Writing Report',
      desc: 'Synthesizing final document',
      state: writerState,
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
            {writerState === 'completed'
              ? 'Research complete'
              : writerState === 'active'
              ? 'Drafting final answer...'
              : consolidatorState === 'active'
              ? 'Cross-referencing sources...'
              : isResearching
              ? 'Gathering web evidence...'
              : plannerState === 'active'
              ? 'Analyzing question...'
              : 'Ready for question'}
          </span>
        </div>

        {/* 4-Step Stepper Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
          {steps.map((step) => {
            const isActive = step.state === 'active';
            const isCompleted = step.state === 'completed';

            return (
              <div
                key={step.num}
                className={`p-3.5 rounded-md border transition-colors ${
                  isActive
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
                  {isActive ? (
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
                  className="px-3.5 py-2 rounded-md bg-[#171719] border border-[#222224] flex items-center justify-between text-xs"
                >
                  <span className="text-white/90 truncate pr-3">{worker.text}</span>
                  <span className="text-xs text-[#4a8ad6] shrink-0 font-medium tabular">
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
