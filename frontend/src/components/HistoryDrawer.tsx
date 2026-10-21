import React, { useState, useEffect, useMemo } from 'react';
import type { ResearchHistoryItem } from '../types';
import { 
  X, 
  Clock, 
  Search, 
  RefreshCw, 
  FileText, 
  ExternalLink, 
  CheckCircle2, 
  AlertTriangle, 
  XCircle, 
  Loader2,
  Sparkles,
  Layers
} from 'lucide-react';

interface HistoryDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectRun: (runId: string) => void;
  currentRunId?: string | null;
}

function formatRelativeTime(isoString?: string | null): string {
  if (!isoString) return 'recently';
  try {
    const diffSec = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
    if (diffSec < 60) return `${Math.max(1, diffSec)}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  } catch {
    return 'recently';
  }
}

export const HistoryDrawer: React.FC<HistoryDrawerProps> = ({
  isOpen,
  onClose,
  onSelectRun,
  currentRunId,
}) => {
  const [runs, setRuns] = useState<ResearchHistoryItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');

  const fetchHistory = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetch('/research/history?limit=50&offset=0');
      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }
      const data = await res.json();
      setRuns(data.runs || []);
      setTotalCount(data.total || 0);
    } catch (err: any) {
      console.warn('Failed fetching research history:', err);
      setError(err.message || 'Unable to load research history');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchHistory();
    }
  }, [isOpen]);

  const filteredRuns = useMemo(() => {
    if (!searchQuery.trim()) return runs;
    const q = searchQuery.toLowerCase();
    return runs.filter(
      r =>
        r.query.toLowerCase().includes(q) ||
        r.run_id.toLowerCase().includes(q) ||
        (r.status && r.status.toLowerCase().includes(q))
    );
  }, [runs, searchQuery]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/75 flex justify-end">
      <div className="w-full max-w-2xl bg-[#131217] border-l border-[#222224] h-full flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#222224] flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <Clock className="w-4 h-4 text-[#4a8ad6] stroke-[1.75]" />
            <div>
              <h3 className="font-semibold text-sm text-white">Research History & Library</h3>
              <p className="text-xs text-[#8a8c92]">
                Recent investigations retained in Redis ({totalCount} active)
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={fetchHistory}
              disabled={isLoading}
              title="Refresh list"
              className="text-[#8a8c92] hover:text-white p-1.5 rounded hover:bg-white/5 transition-colors cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              aria-label="Close history"
              className="text-[#8a8c92] hover:text-white p-1 rounded hover:bg-white/5 transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 24-Hour Retention Banner */}
        <div className="px-6 py-2.5 bg-[#171719] border-b border-[#1b1a1f] flex items-center justify-between text-[11px] text-[#8a8c92]">
          <span className="flex items-center space-x-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#4a8ad6]" />
            <span>24-Hour In-Memory Cache (TTL: 86,400s)</span>
          </span>
          <span className="text-[#8a8c92]/80">Export dossiers to persist permanently</span>
        </div>

        {/* Search & Filter Bar */}
        <div className="p-4 border-b border-[#222224] bg-[#131217]">
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-[#8a8c92]" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search past research queries, run IDs, or statuses..."
              className="w-full bg-[#1b1a1f] border border-[#222224] focus:border-[#4a8ad6] text-white text-xs pl-8 pr-3 py-2 rounded-md outline-none transition-colors placeholder:text-[#5a5c62]"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-[#8a8c92] hover:text-white"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Body / List of Runs */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {isLoading && runs.length === 0 && (
            <div className="py-16 text-center space-y-3">
              <Loader2 className="w-6 h-6 animate-spin text-[#4a8ad6] mx-auto" />
              <p className="text-xs text-[#8a8c92]">Loading recent research runs from cache...</p>
            </div>
          )}

          {error && (
            <div className="p-4 rounded-md bg-[#e5566f]/10 border border-[#e5566f]/30 text-xs text-[#e5566f] flex items-center justify-between">
              <span>{error}</span>
              <button
                onClick={fetchHistory}
                className="underline hover:text-white font-medium cursor-pointer"
              >
                Retry
              </button>
            </div>
          )}

          {!isLoading && !error && filteredRuns.length === 0 && (
            <div className="py-16 text-center space-y-3">
              <div className="w-10 h-10 rounded-full bg-[#212023] flex items-center justify-center mx-auto text-[#8a8c92]">
                <FileText className="w-5 h-5 stroke-[1.5]" />
              </div>
              <p className="text-xs font-medium text-white">No research investigations found</p>
              <p className="text-[11px] text-[#8a8c92] max-w-sm mx-auto">
                {searchQuery
                  ? `No runs matched "${searchQuery}". Try a different search term.`
                  : 'Start a new research investigation from the main studio to populate your dossier library.'}
              </p>
            </div>
          )}

          {filteredRuns.map((run) => {
            const isActive = run.run_id === currentRunId;
            const costVal = run.cost_summary?.total_cost_usd || 0;
            const compositeGrade = run.rag_score?.composite_grade || run.rag_score?.grade;
            const compositeScore = run.rag_score?.composite_score ?? run.rag_score?.overall_score;

            return (
              <div
                key={run.run_id}
                className={`p-3.5 rounded-lg border transition-all ${
                  isActive
                    ? 'bg-[#1b1a1f] border-[#4a8ad6] shadow-sm'
                    : 'bg-[#171719] border-[#222224] hover:border-[#333338]'
                }`}
              >
                {/* Run Top Row: Status + Time */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center space-x-2">
                    {/* Status Pill */}
                    {run.status === 'completed' && (
                      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[11px] font-medium bg-[#44a282]/15 text-[#44a282] border border-[#44a282]/30">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>Completed</span>
                      </span>
                    )}
                    {run.status === 'budget_exceeded' && (
                      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[11px] font-medium bg-[#d9a441]/15 text-[#d9a441] border border-[#d9a441]/30">
                        <AlertTriangle className="w-3 h-3" />
                        <span>Budget Cap</span>
                      </span>
                    )}
                    {run.status === 'failed' && (
                      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[11px] font-medium bg-[#e5566f]/15 text-[#e5566f] border border-[#e5566f]/30">
                        <XCircle className="w-3 h-3" />
                        <span>Failed</span>
                      </span>
                    )}
                    {run.status !== 'completed' && run.status !== 'budget_exceeded' && run.status !== 'failed' && (
                      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[11px] font-medium bg-[#4a8ad6]/15 text-[#4a8ad6] border border-[#4a8ad6]/30">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        <span className="capitalize">{run.status || 'Active'}</span>
                      </span>
                    )}

                    {/* RAG Quality Badge */}
                    {compositeGrade && (
                      <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[11px] font-medium bg-[#4a8ad6]/15 text-[#4a8ad6] border border-[#4a8ad6]/30">
                        <Sparkles className="w-2.5 h-2.5" />
                        <span>Grade {compositeGrade}</span>
                        {compositeScore !== undefined && (
                          <span className="text-white/80 tabular">({compositeScore})</span>
                        )}
                      </span>
                    )}
                  </div>

                  <span className="text-[11px] text-[#8a8c92] tabular">
                    {formatRelativeTime(run.created_at || run.updated_at)}
                  </span>
                </div>

                {/* Query Title */}
                <h4 className="text-xs font-medium text-white mb-2 leading-relaxed line-clamp-2">
                  {run.query}
                </h4>

                {/* Metrics Badges */}
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-[#8a8c92] mb-3">
                  <span className="px-2 py-0.5 rounded bg-[#212023] border border-[#222224] tabular">
                    {run.total_tokens ? `${run.total_tokens.toLocaleString()} tokens` : '0 tokens'}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-[#212023] border border-[#222224] tabular text-[#4a8ad6]">
                    ${costVal.toFixed(4)}
                  </span>
                  {run.findings_count !== undefined && run.findings_count > 0 && (
                    <span className="px-2 py-0.5 rounded bg-[#212023] border border-[#222224] tabular">
                      {run.findings_count} sources
                    </span>
                  )}
                  {run.step_count !== undefined && run.step_count > 0 && (
                    <span className="px-2 py-0.5 rounded bg-[#212023] border border-[#222224] tabular">
                      {run.step_count} steps
                    </span>
                  )}
                  <span className="text-[10px] text-[#6a6c72] font-mono">
                    ID: {run.run_id.slice(0, 8)}
                  </span>
                </div>

                {/* Card Action Footer */}
                <div className="pt-2 border-t border-[#222224] flex items-center justify-between">
                  {/* Load Run Button */}
                  {isActive ? (
                    <span className="inline-flex items-center space-x-1.5 text-xs text-[#4a8ad6] font-medium">
                      <Layers className="w-3.5 h-3.5" />
                      <span>Loaded in Studio</span>
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        onSelectRun(run.run_id);
                        onClose();
                      }}
                      className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-xs font-medium text-white transition-colors cursor-pointer"
                    >
                      <ExternalLink className="w-3 h-3 text-[#4a8ad6]" />
                      <span>Open in Studio</span>
                    </button>
                  )}

                  {/* Direct Export Links if Report Exists */}
                  {run.has_report && (
                    <div className="flex items-center space-x-1.5 text-[11px]">
                      <span className="text-[#6a6c72]">Export:</span>
                      <a
                        href={`/research/${run.run_id}/export?format=pdf`}
                        target="_blank"
                        rel="noreferrer"
                        className="px-1.5 py-0.5 rounded bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors"
                        title="Download PDF Dossier"
                      >
                        PDF
                      </a>
                      <a
                        href={`/research/${run.run_id}/export?format=docx`}
                        target="_blank"
                        rel="noreferrer"
                        className="px-1.5 py-0.5 rounded bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors"
                        title="Download Word Document"
                      >
                        Word
                      </a>
                      <a
                        href={`/research/${run.run_id}/export?format=md`}
                        target="_blank"
                        rel="noreferrer"
                        className="px-1.5 py-0.5 rounded bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors"
                        title="Download Markdown Report"
                      >
                        MD
                      </a>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
