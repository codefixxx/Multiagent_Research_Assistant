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
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/75 flex justify-end">
      <div className="w-full max-w-2xl bg-[#131217] border-l border-[#222224] h-full flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="px-6 py-4.5 border-b border-[#222224] flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <Layers className="w-4 h-4 text-[#4a8ad6] stroke-[1.75]" />
            <div>
              <h3 className="font-semibold text-sm text-white">Activity Details & Diagnostics</h3>
              <p className="text-xs text-[#8a8c92] tabular">
                Run ID: {runId || 'No active run'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close trace"
            className="text-[#8a8c92] hover:text-white p-1 rounded hover:bg-white/5 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Highlights Strip */}
        <div className="px-6 py-3 border-b border-[#1b1a1f] bg-[#171719] grid grid-cols-4 gap-3 text-xs">
          <div>
            <div className="text-xs text-[#8a8c92] mb-0.5">Duration</div>
            <div className="tabular font-medium text-white text-xs">
              {(totalDurationMs / 1000).toFixed(2)}s
            </div>
          </div>
          <div>
            <div className="text-xs text-[#8a8c92] mb-0.5">Tokens</div>
            <div className="tabular font-medium text-white text-xs">
              {totalTokens.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-xs text-[#8a8c92] mb-0.5">Est. Cost</div>
            <div className="tabular font-medium text-[#4a8ad6] text-xs">
              ${totalCostUsd.toFixed(4)}
            </div>
          </div>
          <div>
            <div className="text-xs text-[#8a8c92] mb-0.5">Quality Grade</div>
            <div className="font-medium text-[#5fc39c] text-xs">
              {ragScore?.grade || ragScore?.composite_grade || '--'}
            </div>
          </div>
        </div>

        {/* Navigation Tabs with signature 1px accent indicator */}
        <div className="px-6 border-b border-[#1b1a1f] flex space-x-6 text-xs font-medium">
          <button
            onClick={() => setActiveTab('spans')}
            className={`py-2.5 border-b-2 transition-colors cursor-pointer ${
              activeTab === 'spans'
                ? 'border-[#4a8ad6] text-white'
                : 'border-transparent text-[#8a8c92] hover:text-white'
            }`}
          >
            Execution Steps ({spans.length})
          </button>
          <button
            onClick={() => setActiveTab('economics')}
            className={`py-2.5 border-b-2 transition-colors cursor-pointer ${
              activeTab === 'economics'
                ? 'border-[#4a8ad6] text-white'
                : 'border-transparent text-[#8a8c92] hover:text-white'
            }`}
          >
            Cost & Usage
          </button>
          <button
            onClick={() => setActiveTab('raw')}
            className={`py-2.5 border-b-2 transition-colors cursor-pointer ${
              activeTab === 'raw'
                ? 'border-[#4a8ad6] text-white'
                : 'border-transparent text-[#8a8c92] hover:text-white'
            }`}
          >
            Raw Data
          </button>
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto p-6 text-xs">
          {/* Tab 1: Execution Steps */}
          {activeTab === 'spans' && (
            <div className="space-y-2.5">
              {spans.length === 0 ? (
                <div className="py-16 text-center text-[#8a8c92] italic text-xs">
                  No execution steps recorded for this research run yet.
                </div>
              ) : (
                spans.map((span, idx) => (
                  <div
                    key={span.span_id || idx}
                    className="p-3.5 rounded-md bg-[#171719] border border-[#222224] space-y-1.5"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2">
                        <span className="text-xs font-semibold text-white">
                          {span.name}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-[11px] tabular ${
                          span.status === 'success' || span.status === 'ok'
                            ? 'bg-[#1b2828] text-[#5fc39c]'
                            : 'bg-[#2c1a20] text-[#e5566f]'
                        }`}>
                          {span.status}
                        </span>
                      </div>
                      <span className="text-xs tabular text-[#8a8c92]">
                        {span.duration_ms.toFixed(1)}ms
                      </span>
                    </div>

                    <div className="flex items-center space-x-3 text-xs text-[#8a8c92]">
                      <span>ID: {span.span_id?.slice(0, 10)}</span>
                      {span.parent_span_id && <span>Parent: {span.parent_span_id?.slice(0, 10)}</span>}
                    </div>

                    {span.attributes && Object.keys(span.attributes).length > 0 && (
                      <div className="pt-1 flex flex-wrap gap-1">
                        {Object.entries(span.attributes)
                          .filter(([k]) => k !== 'run_id')
                          .slice(0, 5)
                          .map(([k, v]) => (
                            <span
                              key={k}
                              className="px-1.5 py-0.5 rounded bg-[#212023] text-[11px] text-[#8a8c92]"
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
            <div className="space-y-3">
              {!costSummary || costSummary.stage_attributions.length === 0 ? (
                <div className="py-16 text-center text-[#8a8c92] italic text-xs">
                  Cost and usage data will appear when research stages execute.
                </div>
              ) : (
                <div className="border border-[#222224] rounded-md overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-[#171719] border-b border-[#222224] text-[#8a8c92] font-medium">
                      <tr>
                        <th className="p-2.5">Stage</th>
                        <th className="p-2.5">Model</th>
                        <th className="p-2.5 text-right">Tokens (In / Out)</th>
                        <th className="p-2.5 text-right">Time</th>
                        <th className="p-2.5 text-right">Cost (USD)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#1b1a1f]">
                      {costSummary.stage_attributions.map((attr, idx) => (
                        <tr key={idx} className="hover:bg-[#171719]/50">
                          <td className="p-2.5 text-white capitalize font-medium">
                            {attr.stage}
                          </td>
                          <td className="p-2.5 text-[#8a8c92]">
                            {attr.model}
                          </td>
                          <td className="p-2.5 text-right tabular text-[#8a8c92]">
                            {attr.prompt_tokens} / {attr.completion_tokens}
                          </td>
                          <td className="p-2.5 text-right tabular text-[#8a8c92]">
                            {attr.latency_ms.toFixed(0)}ms
                          </td>
                          <td className="p-2.5 text-right tabular text-[#4a8ad6] font-medium">
                            ${attr.stage_cost_usd.toFixed(4)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="bg-[#171719] border-t border-[#222224] font-medium text-white">
                      <tr>
                        <td colSpan={2} className="p-2.5">Total</td>
                        <td className="p-2.5 text-right tabular">
                          {costSummary.total_prompt_tokens} / {costSummary.total_completion_tokens}
                        </td>
                        <td className="p-2.5 text-right text-[#8a8c92]">--</td>
                        <td className="p-2.5 text-right tabular text-[#4a8ad6] font-semibold">
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
                  className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white text-xs transition-colors cursor-pointer"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-[#5fc39c]" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Copied' : 'Copy JSON'}</span>
                </button>
              </div>
              <pre className="p-3.5 rounded-md bg-[#101217] border border-[#222224] text-xs text-white/80 overflow-x-auto max-h-[500px]">
                <code>{JSON.stringify(spans, null, 2)}</code>
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
