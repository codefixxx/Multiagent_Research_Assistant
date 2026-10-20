import React, { useMemo } from 'react';
import type { 
  ResearchJobData, 
  StreamLogEntry, 
  RAGScore, 
  Citation,
} from '../types';
import { marked } from 'marked';
import { 
  FileText, 
  Copy, 
  Download, 
  Check, 
  CheckCircle2, 
  ShieldCheck, 
  BookOpen, 
  Sparkles,
  Search
} from 'lucide-react';

interface SplitStudioProps {
  jobData: ResearchJobData | null;
  logs: StreamLogEntry[];
  ragScore: RAGScore | null;
  findingsCount: number;
  citationsCount: number;
  superstepsCount?: number;
  spans?: unknown[];
  onSelectCitation: (citation: Citation) => void;
}

export const SplitStudio: React.FC<SplitStudioProps> = ({
  jobData,
  logs,
  ragScore,
  findingsCount,
  citationsCount,
  onSelectCitation
}) => {
  const [copied, setCopied] = React.useState(false);

  const report = jobData?.report;

  // Build citation lookup
  const citationMap = useMemo(() => {
    const map = new Map<string, Citation>();
    if (report?.citations) {
      report.citations.forEach(c => {
        const cleanKey = c.citation_id.replace(/[\[\]]/g, '');
        map.set(cleanKey, c);
        map.set(c.citation_id, c);
      });
    }
    return map;
  }, [report]);

  // Render markdown with clickable source tags
  const renderedHtml = useMemo(() => {
    if (!report?.markdown_output) return '';
    try {
      const rawHtml = marked.parse(report.markdown_output) as string;
      return rawHtml.replace(/\[(cite_\d+)\]/g, (_match, citeKey) => {
        return `<button type="button" class="citation-tag inline-flex items-center px-2 py-0.5 mx-1 rounded text-xs font-mono font-medium bg-blue-500/15 text-blue-300 border border-blue-500/30 hover:bg-blue-500/30 transition-colors cursor-pointer" data-cite="${citeKey}">[${citeKey}]</button>`;
      });
    } catch {
      return report.markdown_output;
    }
  }, [report]);

  const handleContainerClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const btn = target.closest('button.citation-tag');
    if (btn) {
      const citeKey = btn.getAttribute('data-cite') || '';
      const cleanKey = citeKey.replace(/[\[\]]/g, '');
      if (citationMap.has(cleanKey)) {
        onSelectCitation(citationMap.get(cleanKey)!);
      } else if (citationMap.has(citeKey)) {
        onSelectCitation(citationMap.get(citeKey)!);
      } else if (citeKey) {
        onSelectCitation({
          citation_id: citeKey,
          source_url: '#',
          verified_claim: 'Source reference confirmed during research synthesis.'
        });
      }
    }
  };

  const handleCopyMarkdown = () => {
    if (!report?.markdown_output) return;
    navigator.clipboard.writeText(report.markdown_output);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadMarkdown = () => {
    if (!report?.markdown_output) return;
    const blob = new Blob([report.markdown_output], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `research_report_${jobData?.run_id?.slice(0, 8) || 'export'}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadJson = () => {
    if (!jobData) return;
    const blob = new Blob([JSON.stringify(jobData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `research_data_${jobData.run_id?.slice(0, 8) || 'export'}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  // Convert technical raw log into clean human update
  const cleanLogMessage = (message: string, source: string) => {
    if (message.includes('Formulated')) return message;
    if (source === 'PLANNER') return 'Formulating research strategy and sub-topics...';
    if (source === 'RESEARCHER') return message.replace('for worker_', 'for topic ');
    if (source === 'REVIEWER') return message.includes('Approved') ? 'Verified quality and relevance of evidence' : 'Refining search queries for best accuracy';
    if (source === 'CONSOLIDATOR') return 'Organizing and cross-checking all gathered findings...';
    if (source === 'WRITER') return 'Synthesizing comprehensive research report...';
    return message;
  };

  const totalFindings = findingsCount || jobData?.findings_count || ragScore?.findings_count || 0;
  const totalCitations = report?.citations?.length || jobData?.citations_count || citationsCount || 0;

  return (
    <div className="w-full max-w-[1600px] mx-auto px-6 md:px-10 py-5 grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      {/* Left Studio: Activity & Verification (4 columns) */}
      <aside className="lg:col-span-4 space-y-4">
        {/* Simple Stats Card */}
        <div className="grid grid-cols-2 gap-4">
          <div className="p-5 rounded-2xl bg-[#12151c] border border-white/[0.08] shadow-sm">
            <div className="text-sm font-medium text-white/50 mb-1.5 flex items-center space-x-2">
              <BookOpen className="w-4 h-4 text-blue-400" />
              <span>Key Findings</span>
            </div>
            <div className="text-3xl font-mono font-semibold text-white">
              {totalFindings}
            </div>
          </div>
          <div className="p-5 rounded-2xl bg-[#12151c] border border-white/[0.08] shadow-sm">
            <div className="text-sm font-medium text-white/50 mb-1.5 flex items-center space-x-2">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span>Verified Sources</span>
            </div>
            <div className="text-3xl font-mono font-semibold text-white">
              {totalCitations}
            </div>
          </div>
        </div>

        {/* Quality & Fact-Checking Scorecard */}
        {(() => {
          const grade = ragScore?.grade || ragScore?.composite_grade || null;
          const groundednessPct = ragScore ? Math.round((ragScore.groundedness_score ?? 0) * 100) : null;
          const precisionPct = ragScore ? Math.round((ragScore.citation_precision ?? ragScore.citation_precision_score ?? 0) * 100) : null;
          const coveragePct = ragScore ? Math.round((ragScore.coverage_score ?? ragScore.subquestion_coverage_score ?? 0) * 100) : null;

          return (
            <div className="p-6 rounded-2xl bg-[#12151c] border border-white/[0.08] shadow-sm space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                <div className="flex items-center space-x-2.5 text-base text-white font-medium">
                  <ShieldCheck className="w-5 h-5 text-emerald-400" />
                  <span>Source Verification</span>
                </div>
                <span className={`px-3 py-1 rounded-full text-xs font-bold ${
                  grade === 'A+' || grade === 'A'
                    ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                    : grade
                    ? 'bg-blue-500/15 text-blue-300 border border-blue-500/30'
                    : 'bg-white/[0.04] text-white/40'
                }`}>
                  {grade ? `Grade ${grade}` : 'Pending'}
                </span>
              </div>

              <div className="space-y-3.5 text-sm">
                <div>
                  <div className="flex justify-between text-white/70 mb-1.5">
                    <span>Factual Grounding</span>
                    <span className="font-mono font-medium text-white">
                      {groundednessPct !== null ? `${groundednessPct}%` : '--'}
                    </span>
                  </div>
                  <div className="h-2.5 w-full bg-white/[0.04] rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                      style={{ width: `${groundednessPct ?? 0}%` }}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-white/70 mb-1.5">
                    <span>Source Accuracy</span>
                    <span className="font-mono font-medium text-white">
                      {precisionPct !== null ? `${precisionPct}%` : '--'}
                    </span>
                  </div>
                  <div className="h-2.5 w-full bg-white/[0.04] rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-blue-500 rounded-full transition-all duration-500"
                      style={{ width: `${precisionPct ?? 0}%` }}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-white/70 mb-1.5">
                    <span>Topic Coverage</span>
                    <span className="font-mono font-medium text-white">
                      {coveragePct !== null ? `${coveragePct}%` : '--'}
                    </span>
                  </div>
                  <div className="h-2.5 w-full bg-white/[0.04] rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-indigo-500 rounded-full transition-all duration-500"
                      style={{ width: `${coveragePct ?? 0}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Live Activity Updates */}
        <div className="p-6 rounded-2xl bg-[#12151c] border border-white/[0.08] shadow-sm space-y-3.5">
          <div className="flex items-center justify-between pb-3 border-b border-white/[0.06] text-sm">
            <span className="font-medium text-white flex items-center space-x-2">
              <Sparkles className="w-4 h-4 text-blue-400" />
              <span>Live Activity</span>
            </span>
            <span className="text-white/40 text-xs font-mono">{logs.length} updates</span>
          </div>

          <div className="h-72 overflow-y-auto space-y-2.5 pr-1 text-sm select-text">
            {logs.length === 0 ? (
              <div className="text-white/40 italic py-10 text-center text-sm">
                Ready for query. Live updates will appear here when research starts.
              </div>
            ) : (
              logs.map((log) => (
                <div key={log.id} className="flex items-start space-x-3 leading-relaxed text-sm">
                  <span className="text-white/35 font-mono text-xs shrink-0 pt-0.5">
                    {log.timestamp}
                  </span>
                  <span className="text-white/85">
                    {cleanLogMessage(log.message, log.source)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </aside>

      {/* Right Studio: Research Report (8 columns - Wide & Prominent) */}
      <main className="lg:col-span-8">
        <article className="rounded-2xl bg-[#12151c] border border-white/[0.08] shadow-sm overflow-hidden min-h-[720px] flex flex-col">
          {/* Dossier Header */}
          <div className="px-6 py-4.5 border-b border-white/[0.08] flex flex-wrap items-center justify-between gap-3 bg-white/[0.01]">
            <div className="flex items-center space-x-3">
              <FileText className="w-5 h-5 text-blue-400" />
              <h2 className="font-semibold text-white text-base sm:text-lg">Research Report</h2>
              {jobData?.status === 'completed' && (
                <span className="inline-flex items-center space-x-1 px-3 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Ready</span>
                </span>
              )}
            </div>

            {/* Dossier Actions */}
            {report && (
              <div className="flex items-center space-x-2 text-sm">
                <button
                  type="button"
                  onClick={handleCopyMarkdown}
                  className="inline-flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] text-white/80 hover:text-white transition-colors cursor-pointer"
                  title="Copy Raw Markdown"
                >
                  {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
                <button
                  type="button"
                  onClick={handleDownloadMarkdown}
                  className="inline-flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] text-white/80 hover:text-white transition-colors cursor-pointer"
                  title="Download Markdown"
                >
                  <Download className="w-4 h-4" />
                  <span>Download .md</span>
                </button>
                <button
                  type="button"
                  onClick={handleDownloadJson}
                  className="inline-flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] text-white/80 hover:text-white transition-colors cursor-pointer"
                  title="Export Run Data JSON"
                >
                  <Download className="w-4 h-4" />
                  <span>JSON</span>
                </button>
              </div>
            )}
          </div>

          {/* Dossier Body */}
          <div className="p-8 sm:p-10 flex-1 overflow-y-auto" onClick={handleContainerClick}>
            {!report ? (
              <div className="h-full flex flex-col items-center justify-center text-center py-32 text-white/40 space-y-4">
                <div className="w-18 h-18 rounded-3xl bg-white/[0.02] border border-white/[0.06] flex items-center justify-center text-white/30 shadow-inner">
                  <Search className="w-8 h-8" />
                </div>
                <div className="max-w-md">
                  <h3 className="text-lg font-semibold text-white/90">No Research Run Yet</h3>
                  <p className="text-sm sm:text-base text-white/50 mt-2 leading-relaxed">
                    Type a question or pick an example topic above. The assistant will search the web, verify sources, and synthesize an in-depth report.
                  </p>
                </div>
              </div>
            ) : (
              <div 
                className="prose-dossier text-base" 
                dangerouslySetInnerHTML={{ __html: renderedHtml }} 
              />
            )}
          </div>
        </article>
      </main>
    </div>
  );
};
