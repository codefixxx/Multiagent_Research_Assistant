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
      <div className="bg-[#12151c] border border-white/[0.08] rounded-2xl p-5 shadow-sm">
        {/* Simple Stepper Header */}
        <div className="flex items-center justify-between text-sm text-white/50 pb-3 mb-4 border-b border-white/[0.06]">
          <span className="font-semibold text-white/90 uppercase tracking-wider text-xs">
            Research Progress
          </span>
          <span className="text-white/60">
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
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {steps.map((step) => {
            const isActive = step.state === 'active';
            const isCompleted = step.state === 'completed';

            return (
              <div
                key={step.num}
                className={`p-4 rounded-xl border transition-all ${
                  isActive
                    ? 'bg-blue-600/[0.08] border-blue-500/40 shadow-sm ring-1 ring-blue-500/20'
                    : isCompleted
                    ? 'bg-emerald-500/[0.04] border-emerald-500/25'
                    : 'bg-white/[0.02] border-white/[0.05]'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-mono font-medium text-white/40">
                    Step {step.num}
                  </span>
                  {isActive ? (
                    <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-500/15 text-blue-300">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Working</span>
                    </span>
                  ) : isCompleted ? (
                    <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-300">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Done</span>
                    </span>
                  ) : (
                    <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-xs text-white/40">
                      <Clock className="w-3.5 h-3.5" />
                      <span>Waiting</span>
                    </span>
                  )}
                </div>
                <div className="font-semibold text-base text-white/95">{step.title}</div>
                <div className="text-sm text-white/50 mt-1 truncate">{step.desc}</div>
              </div>
            );
          })}
        </div>

        {/* Sub-Topics when active */}
        {workers.length > 0 && (
          <div className="mt-4 pt-4 border-t border-white/[0.06] space-y-2">
            <div className="text-xs font-medium text-white/40 uppercase tracking-wider">
              Investigating Key Angles:
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              {workers.map((worker) => (
                <div
                  key={worker.id}
                  className="px-4 py-2.5 rounded-lg bg-white/[0.02] border border-white/[0.06] flex items-center justify-between text-sm"
                >
                  <span className="text-white/80 truncate pr-3">{worker.text}</span>
                  <span className="font-mono text-sm text-blue-400 shrink-0 font-medium">
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
