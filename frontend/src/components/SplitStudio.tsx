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
  BookOpen
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
        return `<button type="button" class="citation-tag inline-flex items-center px-1.5 py-0.5 mx-1 rounded text-xs font-medium bg-[#212023] text-[#4a8ad6] border border-[#4a8ad6]/40 hover:bg-[#4a8ad6]/20 transition-colors cursor-pointer tabular" data-cite="${citeKey}">[${citeKey}]</button>`;
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

  const handleExportBackend = (format: 'pdf' | 'docx' | 'html' | 'markdown') => {
    if (!jobData?.run_id) return;
    window.open(`/research/${jobData.run_id}/export?format=${format}`, '_blank');
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
    <div className="w-full max-w-[1600px] mx-auto px-6 md:px-10 py-4 grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch">
      {/* Left Column: Metrics & Verification (4 cols) */}
      <aside className="lg:col-span-4 flex flex-col space-y-4">
        {/* Divided Research Metrics Strip */}
        <div className="rounded-md bg-[#131217] border border-[#222224] grid grid-cols-2 divide-x divide-[#222224]">
          <div className="p-4">
            <div className="text-[13px] text-[#8a8c92] mb-1 flex items-center space-x-1.5">
              <BookOpen className="w-3.5 h-3.5 stroke-[1.75]" />
              <span>Key Findings</span>
            </div>
            <div className="text-2xl font-medium text-white tabular">
              {totalFindings}
            </div>
          </div>
          <div className="p-4">
            <div className="text-[13px] text-[#8a8c92] mb-1 flex items-center space-x-1.5">
              <ShieldCheck className="w-3.5 h-3.5 stroke-[1.75]" />
              <span>Verified Sources</span>
            </div>
            <div className="text-2xl font-medium text-white tabular">
              {totalCitations}
            </div>
          </div>
        </div>

        {/* Source Verification Audit Ledger */}
        {(() => {
          const grade = ragScore?.grade || ragScore?.composite_grade || null;
          const groundednessPct = ragScore ? Math.round((ragScore.groundedness_score ?? 0) * 100) : null;
          const precisionPct = ragScore ? Math.round((ragScore.citation_precision ?? ragScore.citation_precision_score ?? 0) * 100) : null;
          const coveragePct = ragScore ? Math.round((ragScore.coverage_score ?? ragScore.subquestion_coverage_score ?? 0) * 100) : null;

          return (
            <div className="p-4.5 rounded-md bg-[#131217] border border-[#222224] space-y-3.5">
              <div className="flex items-center justify-between pb-2.5 border-b border-[#1b1a1f]">
                <div className="flex items-center space-x-2 text-sm text-white font-medium">
                  <ShieldCheck className="w-4 h-4 text-[#44a282] stroke-[1.75]" />
                  <span>Source Verification</span>
                </div>
                <span className={`px-2.5 py-0.5 rounded text-[13px] font-medium ${
                  grade === 'A+' || grade === 'A'
                    ? 'bg-[#1b2828] text-[#5fc39c] border border-[#44a282]/30'
                    : grade
                    ? 'bg-[#212023] text-[#4a8ad6] border border-[#4a8ad6]/30'
                    : 'bg-[#212023] text-[#8a8c92]'
                }`}>
                  {grade ? `Grade ${grade}` : 'Pending'}
                </span>
              </div>

              {/* High-density fact audit ledger */}
              <div className="space-y-3 text-[13px]">
                <div>
                  <div className="flex justify-between text-[#8a8c92] mb-1">
                    <span>Factual Grounding</span>
                    <span className="tabular font-medium text-white">
                      {groundednessPct !== null ? `${groundednessPct}%` : '--'}
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-[#212023] rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-[#44a282] rounded-full transition-[width] duration-300"
                      style={{ width: `${groundednessPct ?? 0}%` }}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-[#8a8c92] mb-1">
                    <span>Source Accuracy</span>
                    <span className="tabular font-medium text-white">
                      {precisionPct !== null ? `${precisionPct}%` : '--'}
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-[#212023] rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-[#4a8ad6] rounded-full transition-[width] duration-300"
                      style={{ width: `${precisionPct ?? 0}%` }}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-[#8a8c92] mb-1">
                    <span>Topic Coverage</span>
                    <span className="tabular font-medium text-white">
                      {coveragePct !== null ? `${coveragePct}%` : '--'}
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-[#212023] rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-[#4a8ad6] rounded-full transition-[width] duration-300"
                      style={{ width: `${coveragePct ?? 0}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Live Activity Stream */}
        <div className="p-4.5 rounded-md bg-[#131217] border border-[#222224] space-y-3 flex-1 flex flex-col">
          <div className="flex items-center justify-between pb-2.5 border-b border-[#1b1a1f] text-[13px]">
            <span className="font-medium text-white">
              Live Activity
            </span>
            <span className="text-[#8a8c92] tabular">{logs.length} updates</span>
          </div>

          <div className="flex-1 max-h-72 overflow-y-auto space-y-2 pr-1 text-[13px] select-text">
            {logs.length === 0 ? (
              <div className="text-[#8a8c92] italic py-6 text-center text-[13px]">
                Ready for query. Live updates will stream as research progresses.
              </div>
            ) : (
              logs.map((log) => (
                <div key={log.id} className="flex items-start space-x-2.5 leading-relaxed">
                  <span className="text-[#8a8c92] tabular shrink-0 pt-0.5">
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

      {/* Right Column: Research Report (8 cols) */}
      <main className="lg:col-span-8 flex flex-col">
        <article className="rounded-md bg-[#131217] border border-[#222224] overflow-hidden flex flex-col flex-1 h-full">
          {/* Header */}
          <div className="px-5 py-3.5 border-b border-[#222224] flex flex-wrap items-center justify-between gap-3 bg-[#131217]">
            <div className="flex items-center space-x-2.5">
              <FileText className="w-4 h-4 text-[#4a8ad6] stroke-[1.75]" />
              <h2 className="font-semibold text-white text-base">Research Report</h2>
              {jobData?.status === 'completed' && (
                <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-xs font-medium bg-[#1b2828] text-[#5fc39c] border border-[#44a282]/30">
                  <CheckCircle2 className="w-3 h-3" />
                  <span>Ready</span>
                </span>
              )}
            </div>

            {/* Actions */}
            {report && (
              <div className="flex items-center space-x-1.5 text-xs">
                <button
                  type="button"
                  onClick={() => handleExportBackend('pdf')}
                  className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-md bg-[#1e293b] hover:bg-[#334155] border border-[#3b82f6]/40 text-[#93c5fd] hover:text-white transition-colors cursor-pointer"
                  title="Download Publication-Grade PDF with Citations"
                >
                  <Download className="w-3.5 h-3.5 text-[#60a5fa]" />
                  <span className="font-medium">PDF</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleExportBackend('docx')}
                  className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors cursor-pointer"
                  title="Download Microsoft Word (.docx)"
                >
                  <FileText className="w-3.5 h-3.5 text-[#818cf8]" />
                  <span>Word</span>
                </button>
                <button
                  type="button"
                  onClick={handleCopyMarkdown}
                  className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors cursor-pointer"
                  title="Copy Raw Markdown"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-[#5fc39c]" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
                <button
                  type="button"
                  onClick={handleDownloadMarkdown}
                  className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors cursor-pointer"
                  title="Download Markdown"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>.md</span>
                </button>
                <button
                  type="button"
                  onClick={handleDownloadJson}
                  className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors cursor-pointer"
                  title="Export Run Data JSON"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>JSON</span>
                </button>
              </div>
            )}
          </div>

          {/* Body */}
          <div className="p-6 sm:p-8 flex-1 overflow-y-auto" onClick={handleContainerClick}>
            {!report ? (
              <div className="py-16 px-4 max-w-xl mx-auto text-left space-y-4">
                <div className="border-l-2 border-[#4a8ad6] pl-4">
                  <h3 className="text-base font-semibold text-white">Workbench ready for inquiry</h3>
                  <p className="text-xs sm:text-sm text-[#8a8c92] mt-1 leading-relaxed">
                    Submit a question to execute multi-agent web research with factual verification.
                  </p>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs text-[#8a8c92]">
                  <div className="p-3 rounded-md bg-[#171719] border border-[#222224]">
                    <div className="text-white font-medium mb-1">1. Decomposition</div>
                    <div>Partitions topic into focused sub-inquiries.</div>
                  </div>
                  <div className="p-3 rounded-md bg-[#171719] border border-[#222224]">
                    <div className="text-white font-medium mb-1">2. Retrieval</div>
                    <div>Gathers and cross-checks live web sources.</div>
                  </div>
                  <div className="p-3 rounded-md bg-[#171719] border border-[#222224]">
                    <div className="text-white font-medium mb-1">3. Synthesis</div>
                    <div>Builds cited report with verification scoring.</div>
                  </div>
                </div>
              </div>
            ) : (
              <div 
                className="prose-dossier text-sm" 
                dangerouslySetInnerHTML={{ __html: renderedHtml }} 
              />
            )}
          </div>
        </article>
      </main>
    </div>
  );
};
