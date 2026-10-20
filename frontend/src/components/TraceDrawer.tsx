import React, { useState } from 'react';
import type { TraceSpan, RunCostSummary, RAGScore } from '../types';
import { X, Layers, Copy, Check } from 'lucide-react';

interface TraceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  runId: string | null;
  spans: TraceSpan[];
  costSummary: RunCostSummary | null;
  ragScore: RAGScore | null;
}

export const TraceDrawer: React.FC<TraceDrawerProps> = ({
  isOpen,
  onClose,
  runId,
  spans,
  costSummary,
  ragScore
}) => {
  const [activeTab, setActiveTab] = useState<'spans' | 'economics' | 'raw'>('spans');
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const totalDurationMs = spans.reduce((acc, s) => acc + (s.duration_ms || 0), 0);
  const totalTokens = (costSummary?.total_prompt_tokens || 0) + (costSummary?.total_completion_tokens || 0);
  const totalCostUsd = costSummary?.total_cost_usd || 0;

  const handleCopyJson = () => {
    navigator.clipboard.writeText(JSON.stringify(spans, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-xs flex justify-end">
      <div className="w-full max-w-2xl bg-[#101217] border-l border-white/[0.08] shadow-2xl h-full flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="px-6 py-5 border-b border-white/[0.08] flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <Layers className="w-5 h-5 text-blue-400" />
            <div>
              <h3 className="font-semibold text-base text-white">Activity Details & Diagnostics</h3>
              <p className="text-xs font-mono text-white/50">
                Run ID: {runId || 'No active run'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close trace"
            className="text-white/40 hover:text-white p-1.5 rounded-lg hover:bg-white/5 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Highlights Strip */}
        <div className="px-6 py-4 border-b border-white/[0.06] bg-white/[0.01] grid grid-cols-4 gap-3 text-sm">
          <div>
            <div className="text-xs text-white/40 mb-1">Duration</div>
            <div className="font-mono tabular font-medium text-white/90 text-sm">
              {(totalDurationMs / 1000).toFixed(2)}s
            </div>
          </div>
          <div>
            <div className="text-xs text-white/40 mb-1">Tokens</div>
            <div className="font-mono tabular font-medium text-white/90 text-sm">
              {totalTokens.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-xs text-white/40 mb-1">Est. Cost</div>
            <div className="font-mono tabular font-medium text-blue-400 text-sm">
              ${totalCostUsd.toFixed(4)}
            </div>
          </div>
          <div>
            <div className="text-xs text-white/40 mb-1">Quality Grade</div>
            <div className="font-mono font-medium text-emerald-400 text-sm">
              {ragScore?.grade || ragScore?.composite_grade || '--'}
            </div>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="px-6 border-b border-white/[0.06] flex space-x-6 text-sm font-medium">
          <button
            onClick={() => setActiveTab('spans')}
            className={`py-3 border-b-2 transition-colors cursor-pointer ${
              activeTab === 'spans'
                ? 'border-blue-500 text-white'
                : 'border-transparent text-white/40 hover:text-white/70'
            }`}
          >
            Execution Steps ({spans.length})
          </button>
          <button
            onClick={() => setActiveTab('economics')}
            className={`py-3 border-b-2 transition-colors cursor-pointer ${
              activeTab === 'economics'
                ? 'border-blue-500 text-white'
                : 'border-transparent text-white/40 hover:text-white/70'
            }`}
          >
            Cost & Usage
          </button>
          <button
            onClick={() => setActiveTab('raw')}
            className={`py-3 border-b-2 transition-colors cursor-pointer ${
              activeTab === 'raw'
                ? 'border-blue-500 text-white'
                : 'border-transparent text-white/40 hover:text-white/70'
            }`}
          >
            Raw Data
          </button>
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto p-6 text-sm">
          {/* Tab 1: Execution Steps */}
          {activeTab === 'spans' && (
            <div className="space-y-3">
              {spans.length === 0 ? (
                <div className="py-20 text-center text-white/30 italic text-sm">
                  No execution steps recorded for this research run yet.
                </div>
              ) : (
                spans.map((span, idx) => (
                  <div
                    key={span.span_id || idx}
                    className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2.5">
                        <span className="font-mono text-sm font-semibold text-white/95">
                          {span.name}
                        </span>
                        <span className={`px-2 py-0.5 rounded text-xs font-mono ${
                          span.status === 'success' || span.status === 'ok'
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : 'bg-rose-500/10 text-rose-400'
                        }`}>
                          {span.status}
                        </span>
                      </div>
                      <span className="font-mono text-xs tabular text-white/60">
                        {span.duration_ms.toFixed(1)}ms
                      </span>
                    </div>

                    <div className="flex items-center space-x-4 text-xs font-mono text-white/40">
                      <span>ID: {span.span_id?.slice(0, 10)}</span>
                      {span.parent_span_id && <span>Parent: {span.parent_span_id?.slice(0, 10)}</span>}
                    </div>

                    {span.attributes && Object.keys(span.attributes).length > 0 && (
                      <div className="pt-1 flex flex-wrap gap-1.5">
                        {Object.entries(span.attributes)
                          .filter(([k]) => k !== 'run_id')
                          .slice(0, 5)
                          .map(([k, v]) => (
                            <span
                              key={k}
                              className="px-2 py-0.5 rounded bg-white/[0.03] text-xs font-mono text-white/70"
                            >
                              {k}: <span className="text-white/90">{String(v).slice(0, 35)}</span>
                            </span>
                          ))}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          {/* Tab 2: Cost Attribution Table */}
          {activeTab === 'economics' && (
            <div className="space-y-4">
              {!costSummary || costSummary.stage_attributions.length === 0 ? (
                <div className="py-20 text-center text-white/30 italic text-sm">
                  Cost and usage data will appear when research stages execute.
                </div>
              ) : (
                <div className="border border-white/[0.08] rounded-xl overflow-hidden">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-white/[0.02] border-b border-white/[0.06] text-white/50 font-medium">
                      <tr>
                        <th className="p-3">Stage</th>
                        <th className="p-3">Model</th>
                        <th className="p-3 text-right">Tokens (In / Out)</th>
                        <th className="p-3 text-right">Time</th>
                        <th className="p-3 text-right">Cost (USD)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.04]">
                      {costSummary.stage_attributions.map((attr, idx) => (
                        <tr key={idx} className="hover:bg-white/[0.01]">
                          <td className="p-3 text-white/95 capitalize font-medium">
                            {attr.stage}
                          </td>
                          <td className="p-3 font-mono text-xs text-white/70">
                            {attr.model}
                          </td>
                          <td className="p-3 font-mono text-right tabular text-white/80">
                            {attr.prompt_tokens} / {attr.completion_tokens}
                          </td>
                          <td className="p-3 font-mono text-right tabular text-white/60">
                            {attr.latency_ms.toFixed(0)}ms
                          </td>
                          <td className="p-3 font-mono text-right tabular text-blue-400 font-medium">
                            ${attr.stage_cost_usd.toFixed(4)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="bg-white/[0.02] border-t border-white/[0.08] font-medium text-white/95">
                      <tr>
                        <td colSpan={2} className="p-3">Total</td>
                        <td className="p-3 font-mono text-right tabular">
                          {costSummary.total_prompt_tokens} / {costSummary.total_completion_tokens}
                        </td>
                        <td className="p-3 font-mono text-right text-white/40">--</td>
                        <td className="p-3 font-mono text-right tabular text-blue-400 font-semibold">
                          ${costSummary.total_cost_usd.toFixed(4)}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Tab 3: Raw Data */}
          {activeTab === 'raw' && (
            <div className="space-y-3">
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={handleCopyJson}
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.07] border border-white/[0.08] text-white/70 hover:text-white text-xs transition-colors cursor-pointer"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Copied' : 'Copy JSON'}</span>
                </button>
              </div>
              <pre className="p-4 rounded-xl bg-[#0c0d12] border border-white/[0.06] font-mono text-xs text-white/75 overflow-x-auto max-h-[500px]">
                {JSON.stringify(spans, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
