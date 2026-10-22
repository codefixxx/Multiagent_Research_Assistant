import React, { useState, useEffect } from 'react';
import type { ResearchPlan, SubQuestion } from '../types';
import { 
  CheckCircle2, 
  Sparkles, 
  RotateCcw, 
  XCircle, 
  Plus, 
  Trash2, 
  HelpCircle, 
  Tag, 
  Play, 
  Loader2, 
  SlidersHorizontal 
} from 'lucide-react';

interface PlanSteeringCardProps {
  initialPlan?: ResearchPlan | null;
  onSteer: (
    action: 'approve' | 'modify' | 'regenerate' | 'reject',
    modifiedPlan?: ResearchPlan,
    feedback?: string
  ) => Promise<boolean>;
  isSubmitting?: boolean;
}

export const PlanSteeringCard: React.FC<PlanSteeringCardProps> = ({
  initialPlan,
  onSteer,
  isSubmitting = false
}) => {
  const [objective, setObjective] = useState('');
  const [subQuestions, setSubQuestions] = useState<SubQuestion[]>([]);
  const [feedback, setFeedback] = useState('');
  const [newTagInput, setNewTagInput] = useState<{ [key: string]: string }>({});
  const [hasUserEdited, setHasUserEdited] = useState(false);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const initializedPlanRef = React.useRef<string | null>(null);

  // Sync initial plan without overwriting active human edits during background polling
  useEffect(() => {
    if (!initialPlan) return;
    const planKey = JSON.stringify(initialPlan);
    if (initializedPlanRef.current !== planKey && !hasUserEdited) {
      initializedPlanRef.current = planKey;
      setObjective(initialPlan.objective || '');
      setSubQuestions(
        initialPlan.sub_questions && initialPlan.sub_questions.length > 0
          ? JSON.parse(JSON.stringify(initialPlan.sub_questions))
          : []
      );
    }
  }, [initialPlan, hasUserEdited]);

  const handleUpdateQuestion = (idx: number, field: keyof SubQuestion, value: any) => {
    setHasUserEdited(true);
    setSubQuestions(prev => {
      const copy = [...prev];
      copy[idx] = { ...copy[idx], [field]: value };
      return copy;
    });
  };

  const handleAddSubQuestion = () => {
    if (subQuestions.length >= 4) return;
    setHasUserEdited(true);
    const newId = `subq_${Date.now()}`;
    setSubQuestions(prev => [
      ...prev,
      {
        id: newId,
        question: 'New custom sub-topic investigation',
        rationale: 'Clarifies key aspect required for thorough conclusion',
        search_queries: ['relevant keywords and data sources']
      }
    ]);
  };

  const handleRemoveSubQuestion = (idx: number) => {
    if (subQuestions.length <= 1) return;
    setHasUserEdited(true);
    setSubQuestions(prev => prev.filter((_, i) => i !== idx));
  };

  const handleAddQueryTag = (subqIdx: number) => {
    const subqId = subQuestions[subqIdx]?.id || String(subqIdx);
    const text = (newTagInput[subqId] || '').trim();
    if (!text) return;
    setHasUserEdited(true);
    setSubQuestions(prev => {
      const copy = [...prev];
      const existingQueries = copy[subqIdx].search_queries || [];
      copy[subqIdx] = {
        ...copy[subqIdx],
        search_queries: [...existingQueries, text]
      };
      return copy;
    });
    setNewTagInput(prev => ({ ...prev, [subqId]: '' }));
  };

  const handleRemoveQueryTag = (subqIdx: number, queryIdx: number) => {
    setHasUserEdited(true);
    setSubQuestions(prev => {
      const copy = [...prev];
      copy[subqIdx] = {
        ...copy[subqIdx],
        search_queries: copy[subqIdx].search_queries.filter((_, i) => i !== queryIdx)
      };
      return copy;
    });
  };

  const handleResetToOriginal = () => {
    if (initialPlan) {
      setObjective(initialPlan.objective || '');
      setSubQuestions(
        initialPlan.sub_questions && initialPlan.sub_questions.length > 0
          ? JSON.parse(JSON.stringify(initialPlan.sub_questions))
          : []
      );
      setNewTagInput({});
      setHasUserEdited(false);
    }
  };

  const handleApprove = async () => {
    if (hasUserEdited) {
      await handleModifyAndProceed();
      return;
    }
    setPendingAction('approve');
    await onSteer('approve');
    setPendingAction(null);
  };

  const handleModifyAndProceed = async () => {
    setPendingAction('modify');
    const flushedSubqs = subQuestions.map((subq, sIdx) => {
      const subqId = subq.id || String(sIdx);
      const pendingText = (newTagInput[subqId] || '').trim();
      const queries = [...(subq.search_queries || [])];
      if (pendingText && !queries.includes(pendingText)) {
        queries.push(pendingText);
      }
      return {
        ...subq,
        question: subq.question.trim() || `Investigation angle #${sIdx + 1}`,
        rationale: subq.rationale.trim() || 'Required for comprehensive conclusion',
        search_queries: queries.length > 0 ? queries : [subq.question.trim() || initialPlan?.query || 'web search']
      };
    });

    const modifiedPlan: ResearchPlan = {
      query: initialPlan?.query || '',
      objective: objective.trim() || initialPlan?.objective || '',
      sub_questions: flushedSubqs
    };
    await onSteer('modify', modifiedPlan);
    setPendingAction(null);
  };

  const handleRegenerate = async () => {
    setPendingAction('regenerate');
    await onSteer('regenerate', undefined, feedback.trim());
    setPendingAction(null);
  };

  const handleReject = async () => {
    setPendingAction('reject');
    await onSteer('reject');
    setPendingAction(null);
  };

  return (
    <div className="rounded-lg bg-[#131217] border border-[#d9a441]/40 p-5 sm:p-6 shadow-xl space-y-5 animate-in fade-in duration-200">
      {/* Header Banner */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-[#222224]">
        <div className="flex items-center space-x-3">
          <div className="p-2 rounded-md bg-[#d9a441]/20 text-[#d9a441] border border-[#d9a441]/40">
            <Sparkles className="w-5 h-5 stroke-[2]" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h3 className="font-semibold text-white text-base">
                Human-in-the-Loop Plan Steering
              </h3>
              <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-[#d9a441]/20 text-[#d9a441] border border-[#d9a441]/40 animate-pulse">
                Paused for Decision
              </span>
            </div>
            <p className="text-xs text-[#8a8c92] mt-0.5">
              Review the Planner&apos;s decomposed strategy, edit queries, or direct re-planning before research fanout.
            </p>
          </div>
        </div>

        {/* Quick Steer Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {hasUserEdited ? (
            <>
              <button
                type="button"
                onClick={handleModifyAndProceed}
                disabled={isSubmitting || pendingAction !== null}
                className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-md bg-[#2568b2] hover:bg-[#1e5494] text-white text-xs font-medium transition-colors cursor-pointer shadow-md disabled:opacity-50"
              >
                {pendingAction === 'modify' ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Play className="w-3.5 h-3.5 fill-current" />
                )}
                <span>Apply Custom Plan &amp; Start</span>
              </button>
              <button
                type="button"
                onClick={handleResetToOriginal}
                disabled={isSubmitting || pendingAction !== null}
                className="inline-flex items-center space-x-1.5 px-3 py-2 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
                title="Discard edits and restore original plan"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Reset Edits</span>
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={handleApprove}
              disabled={isSubmitting || pendingAction !== null}
              className="inline-flex items-center space-x-1.5 px-4 py-2 rounded-md bg-[#2568b2] hover:bg-[#1e5494] text-white text-xs font-medium transition-colors cursor-pointer shadow-md disabled:opacity-50"
            >
              {pendingAction === 'approve' ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="w-3.5 h-3.5" />
              )}
              <span>Approve Plan &amp; Start</span>
            </button>
          )}

          <button
            type="button"
            onClick={handleReject}
            disabled={isSubmitting || pendingAction !== null}
            className="inline-flex items-center space-x-1.5 px-3 py-2 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#e5566f] hover:text-[#ff788f] text-xs font-medium transition-colors cursor-pointer disabled:opacity-50"
            title="Cancel this research run"
          >
            {pendingAction === 'reject' ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <XCircle className="w-3.5 h-3.5" />
            )}
            <span>Cancel Run</span>
          </button>
        </div>
      </div>

      {/* Primary Objective Input */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-[#8a8c92] flex items-center space-x-1.5">
          <SlidersHorizontal className="w-3.5 h-3.5 text-[#4a8ad6]" />
          <span>Synthesized Research Objective:</span>
        </label>
        <textarea
          value={objective}
          onChange={(e) => {
            setObjective(e.target.value);
            setHasUserEdited(true);
          }}
          rows={2}
          placeholder="Overall objective that research synthesis must fulfill..."
          className="w-full bg-[#171719] border border-[#222224] focus:border-[#4a8ad6] rounded-md px-3.5 py-2 text-xs text-white placeholder-[#8a8c92]/50 focus:outline-none transition-colors resize-none leading-relaxed"
        />
      </div>

      {/* Sub-Questions Cards List */}
      <div className="space-y-3">
        <div className="flex items-center justify-between text-xs text-[#8a8c92]">
          <span className="font-medium text-white flex items-center space-x-1.5">
            <HelpCircle className="w-3.5 h-3.5 text-[#4a8ad6]" />
            <span>Parallel Investigation Angles ({subQuestions.length} of 4):</span>
          </span>
          {subQuestions.length < 4 && (
            <button
              type="button"
              onClick={handleAddSubQuestion}
              className="inline-flex items-center space-x-1 text-xs text-[#4a8ad6] hover:text-[#7bb0f0] transition-colors cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>Add Sub-Question</span>
            </button>
          )}
        </div>

        <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
          {subQuestions.map((subq, sIdx) => {
            const subqId = subq.id || String(sIdx);
            return (
              <div
                key={subqId}
                className="p-3.5 rounded-md bg-[#171719] border border-[#222224] space-y-2.5 relative group hover:border-[#333338] transition-colors"
              >
                {/* Topic Index & Delete */}
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold tracking-wider text-[#4a8ad6] uppercase">
                    Topic Angle #{sIdx + 1}
                  </span>
                  {subQuestions.length > 1 && (
                    <button
                      type="button"
                      onClick={() => handleRemoveSubQuestion(sIdx)}
                      className="text-[#8a8c92] hover:text-[#e5566f] transition-colors p-1 rounded"
                      title="Remove this sub-question"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {/* Question Input */}
                <div>
                  <input
                    type="text"
                    value={subq.question}
                    onChange={(e) => handleUpdateQuestion(sIdx, 'question', e.target.value)}
                    placeholder="Specific investigation question..."
                    className="w-full bg-[#131217] border border-[#222224] focus:border-[#4a8ad6] rounded px-3 py-1.5 text-xs text-white placeholder-[#8a8c92]/50 focus:outline-none transition-colors"
                  />
                </div>

                {/* Rationale Input */}
                <div>
                  <input
                    type="text"
                    value={subq.rationale}
                    onChange={(e) => handleUpdateQuestion(sIdx, 'rationale', e.target.value)}
                    placeholder="Rationale / why this evidence matters..."
                    className="w-full bg-[#131217] border border-[#222224] focus:border-[#4a8ad6] rounded px-3 py-1 text-[11px] text-[#8a8c92] placeholder-[#8a8c92]/40 focus:outline-none transition-colors"
                  />
                </div>

                {/* Search Queries Tag Pills */}
                <div className="space-y-1.5 pt-1">
                  <div className="text-[11px] text-[#8a8c92] flex items-center space-x-1">
                    <Tag className="w-3 h-3 text-[#8a8c92]" />
                    <span>Targeted Search Queries:</span>
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    {(subq.search_queries || []).map((qStr, qIdx) => (
                      <span
                        key={qIdx}
                        className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[11px] bg-[#212023] text-white/90 border border-[#2b2a30]"
                      >
                        <span className="truncate max-w-[200px]">{qStr}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveQueryTag(sIdx, qIdx)}
                          className="text-[#8a8c92] hover:text-white ml-0.5"
                        >
                          &times;
                        </button>
                      </span>
                    ))}

                    {/* Quick Add Tag Input */}
                    <div className="inline-flex items-center space-x-1">
                      <input
                        type="text"
                        value={newTagInput[subqId] || ''}
                        onChange={(e) => setNewTagInput(prev => ({ ...prev, [subqId]: e.target.value }))}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleAddQueryTag(sIdx);
                          }
                        }}
                        placeholder="+ query keyword"
                        className="bg-[#131217] border border-[#222224] focus:border-[#4a8ad6] rounded px-2 py-0.5 text-[11px] text-white placeholder-[#8a8c92]/50 focus:outline-none w-28"
                      />
                      <button
                        type="button"
                        onClick={() => handleAddQueryTag(sIdx)}
                        disabled={!(newTagInput[subqId] || '').trim()}
                        className="px-1.5 py-0.5 rounded bg-[#212023] hover:bg-[#2a292e] text-[#4a8ad6] hover:text-white border border-[#2b2a30] disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-[11px] flex items-center space-x-0.5"
                        title="Add query keyword"
                      >
                        <Plus className="w-3 h-3" />
                        <span>Add</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Re-planning Guidance Section */}
      <div className="pt-3 border-t border-[#222224] space-y-2">
        <label className="text-xs font-medium text-[#8a8c92] flex items-center space-x-1.5">
          <RotateCcw className="w-3.5 h-3.5 text-[#d9a441]" />
          <span>Steering Feedback (Instruct Planner to re-generate with constraints):</span>
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && feedback.trim() && !isSubmitting) {
                e.preventDefault();
                handleRegenerate();
              }
            }}
            placeholder="e.g. 'Narrow focus to 2025-2026 benchmarks only, exclude marketing whitepapers'"
            disabled={isSubmitting || pendingAction !== null}
            className="flex-1 bg-[#171719] border border-[#222224] focus:border-[#d9a441] rounded-md px-3.5 py-2 text-xs text-white placeholder-[#8a8c92]/50 focus:outline-none transition-colors"
          />
          <button
            type="button"
            onClick={handleRegenerate}
            disabled={!feedback.trim() || isSubmitting || pendingAction !== null}
            className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#d9a441]/40 text-[#d9a441] hover:text-[#f3c25b] text-xs font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            {pendingAction === 'regenerate' ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RotateCcw className="w-3.5 h-3.5" />
            )}
            <span>Regenerate Plan</span>
          </button>
        </div>
      </div>
    </div>
  );
};
