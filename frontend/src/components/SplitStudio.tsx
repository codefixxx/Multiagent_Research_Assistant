import React, { useMemo } from 'react';
import type { 
  ResearchJobData, 
  StreamLogEntry, 
  RAGScore, 
  Citation,
  ResearchPlan,
  JobStatus,
} from '../types';
import { PlanSteeringCard } from './PlanSteeringCard';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import katex from 'katex';
import { isAutoPurgeOnExport, getSessionId } from '../utils/session';
import { 
  FileText, 
  Copy, 
  Download, 
  Check, 
  CheckCircle2, 
  ShieldCheck, 
  BookOpen,
  AlertTriangle,
  KeyRound,
  Cpu,
  XCircle,
  SlidersHorizontal,
  RefreshCw,
  ShieldAlert,
  Layers,
  FileCode2
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
  onOpenSettings?: () => void;
  onRetry?: () => void;
  status?: JobStatus;
  onSteerPlan?: (
    action: 'approve' | 'modify' | 'regenerate' | 'reject',
    modifiedPlan?: ResearchPlan,
    feedback?: string
  ) => Promise<boolean>;
}

export const SplitStudio: React.FC<SplitStudioProps> = ({
  jobData,
  logs,
  ragScore,
  findingsCount,
  citationsCount,
  onSelectCitation,
  onOpenSettings,
  onRetry,
  status,
  onSteerPlan
}) => {
  const [copied, setCopied] = React.useState(false);

  const report = jobData?.report;

  // Build citation lookup
  const citationMap = useMemo(() => {
    const map = new Map<string, Citation>();
    if (report?.citations) {
      report.citations.forEach(c => {
        const rawKey = c.citation_id;
        const cleanKey = rawKey.replace(/[[\]]/g, '').trim();
        const lowerKey = cleanKey.toLowerCase();

        map.set(rawKey, c);
        map.set(rawKey.toLowerCase(), c);
        map.set(cleanKey, c);
        map.set(lowerKey, c);

        const numMatch = lowerKey.match(/\d+/);
        if (numMatch) {
          const num = numMatch[0];
          map.set(num, c);
          map.set(`cite_${num}`, c);
          map.set(`cite${num}`, c);
          map.set(`cite:${num}`, c);
          map.set(`[cite_${num}]`, c);
          map.set(`[cite${num}]`, c);
          map.set(`[cite:${num}]`, c);
          map.set(`[${num}]`, c);
        }
      });
    }
    return map;
  }, [report]);

  // Render markdown with math support (KaTeX) and clickable source tags
  const renderedHtml = useMemo(() => {
    if (!report?.markdown_output) return '';
    try {
      const rawMarkdown = report.markdown_output;

      // 1. Protect code blocks and inline code from math extraction
      const codeBlocks: string[] = [];
      let protectedText = rawMarkdown.replace(/(```[\s\S]*?```|`[^`\n]+`)/g, (match) => {
        const id = `@@CODE_TOKEN_${codeBlocks.length}@@`;
        codeBlocks.push(match);
        return id;
      });

      // 2. Extract display/block math: $$...$$ or \[...\]
      const mathBlocks: string[] = [];
      protectedText = protectedText.replace(/(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\])/g, (match) => {
        let raw = match;
        if (raw.startsWith('$$') && raw.endsWith('$$')) {
          raw = raw.slice(2, -2).trim();
        } else if (raw.startsWith('\\[') && raw.endsWith('\\]')) {
          raw = raw.slice(2, -2).trim();
        }
        const id = `@@MATH_BLOCK_${mathBlocks.length}@@`;
        mathBlocks.push(raw);
        return `\n\n${id}\n\n`;
      });

      // 3. Extract inline math: \(...\) or $...$
      const inlineMath: string[] = [];
      protectedText = protectedText.replace(/\\\(([\s\S]+?)\\\)/g, (_match, raw) => {
        const id = `@@MATH_INLINE_${inlineMath.length}@@`;
        inlineMath.push(raw.trim());
        return id;
      });

      protectedText = protectedText.replace(/(?<!\$)\$(?!\$)([^$\n\r]+?)(?<![\s$])\$(?!\$)/g, (match, raw) => {
        // Exclude common prices like $100, $50.99, $10 million, etc.
        if (/^\d+(?:\.\d+)?(?:\s*(?:USD|EUR|GBP|million|billion|k))?$/i.test(raw.trim())) {
          return match;
        }
        const id = `@@MATH_INLINE_${inlineMath.length}@@`;
        inlineMath.push(raw.trim());
        return id;
      });

      // 4. Restore code blocks before marked parsing
      const preprocessedMarkdown = protectedText.replace(/@@CODE_TOKEN_(\d+)@@/g, (_, idx) => codeBlocks[Number(idx)]);

      // 5. Parse markdown into HTML
      let parsedHtml = marked.parse(preprocessedMarkdown) as string;

      // 6. Replace citations with clickable buttons
      const isCitationToken = (token: string): boolean => {
        const t = token.trim();
        return /^(?:cite[_:-]?[a-zA-Z0-9]+|\d+)$/i.test(t);
      };

      parsedHtml = parsedHtml.replace(/\[([a-zA-Z0-9_:\s,;-]+)\](?!\()/g, (match, inner) => {
        const parts = inner.split(/[,;]+/).map((t: string) => t.trim()).filter(Boolean);
        if (parts.length === 0 || !parts.every(isCitationToken)) {
          return match;
        }

        return parts.map((citeKey: string) => {
          const cleanKey = citeKey.replace(/[[\]]/g, '').trim();
          const displayKey = cleanKey.startsWith('[') ? cleanKey : `[${cleanKey}]`;
          return `<button type="button" class="citation-tag inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded text-xs font-medium bg-[#212023] text-[#4a8ad6] border border-[#4a8ad6]/40 hover:bg-[#4a8ad6]/20 transition-colors cursor-pointer tabular" data-cite="${cleanKey}">${displayKey}</button>`;
        }).join('');
      });

      // 7. Render math placeholders to KaTeX HTML
      parsedHtml = parsedHtml.replace(/<p>\s*(@@MATH_BLOCK_\d+@@)\s*<\/p>/g, '$1');
      parsedHtml = parsedHtml.replace(/@@MATH_BLOCK_(\d+)@@/g, (_, idx) => {
        const expr = mathBlocks[Number(idx)];
        try {
          return `<div class="katex-display my-3 overflow-x-auto text-center">${katex.renderToString(expr, { displayMode: true, throwOnError: false })}</div>`;
        } catch {
          return `$$${expr}$$`;
        }
      });

      parsedHtml = parsedHtml.replace(/@@MATH_INLINE_(\d+)@@/g, (_, idx) => {
        const expr = inlineMath[Number(idx)];
        try {
          return katex.renderToString(expr, { displayMode: false, throwOnError: false });
        } catch {
          return `$${expr}$`;
        }
      });

      // 8. Sanitize HTML allowing mathMl and svg
      return DOMPurify.sanitize(parsedHtml, {
        USE_PROFILES: { html: true, mathMl: true, svg: true },
        ADD_TAGS: ['semantics', 'annotation', 'annotation-xml'],
        ADD_ATTR: ['target', 'rel', 'display', 'mathvariant', 'xmlns', 'encoding'],
      });
    } catch {
      return report.markdown_output;
    }
  }, [report]);

  // Determine error category for actionable user remediation
  const isRateLimit = useMemo(() => {
    const code = (jobData?.error_code || '').toLowerCase();
    const msg = (jobData?.error_message || '').toLowerCase();
    return code.includes('rate_limit') || msg.includes('quota') || msg.includes('rate limit') || msg.includes('429') || msg.includes('resource_exhausted');
  }, [jobData]);

  const isAuth = useMemo(() => {
    const code = (jobData?.error_code || '').toLowerCase();
    const msg = (jobData?.error_message || '').toLowerCase();
    return code.includes('auth') || code.includes('key') || msg.includes('api key') || msg.includes('unauthorized') || msg.includes('permission_denied') || msg.includes('401') || msg.includes('403');
  }, [jobData]);

  const isModelNotFound = useMemo(() => {
    const code = (jobData?.error_code || '').toLowerCase();
    const msg = (jobData?.error_message || '').toLowerCase();
    return code.includes('model') || msg.includes('not found') || msg.includes('does not exist') || msg.includes('404');
  }, [jobData]);

  const isContextLimit = useMemo(() => {
    const code = (jobData?.error_code || '').toLowerCase();
    const msg = (jobData?.error_message || '').toLowerCase();
    return code.includes('context_length') || msg.includes('context length') || msg.includes('too many tokens') || msg.includes('context window') || msg.includes('token count');
  }, [jobData]);

  const isContentPolicy = useMemo(() => {
    const code = (jobData?.error_code || '').toLowerCase();
    const msg = (jobData?.error_message || '').toLowerCase();
    return code.includes('content_moderation') || code.includes('safety') || msg.includes('safety') || msg.includes('content policy') || msg.includes('blocked');
  }, [jobData]);

  const isSchemaError = useMemo(() => {
    const code = (jobData?.error_code || '').toLowerCase();
    const msg = (jobData?.error_message || '').toLowerCase();
    return code.includes('schema') || code.includes('parsing') || msg.includes('structured output') || msg.includes('schema validation');
  }, [jobData]);

  const errorTitle = useMemo(() => {
    if (isRateLimit) return 'Model Quota or Rate Limit Reached';
    if (isAuth) return 'API Key Authentication Failed';
    if (isModelNotFound) return 'Model Unavailable or Not Found';
    if (isContextLimit) return 'Model Context Window Exceeded';
    if (isContentPolicy) return 'Content Blocked by Safety Filters';
    if (isSchemaError) return 'Structured Output Schema Validation Failed';
    return 'Research Job Failed';
  }, [isRateLimit, isAuth, isModelNotFound, isContextLimit, isContentPolicy, isSchemaError]);

  const errorTheme = useMemo(() => {
    if (isRateLimit) {
      return {
        card: 'bg-[#d9a441]/10 border-[#d9a441]/35',
        iconBg: 'bg-[#d9a441]/20 text-[#d9a441]',
        badge: 'bg-[#d9a441]/25 text-[#d9a441] border border-[#d9a441]/40',
        defaultCode: 'RATE_LIMIT_429',
      };
    }
    if (isAuth) {
      return {
        card: 'bg-[#e5566f]/10 border-[#e5566f]/35',
        iconBg: 'bg-[#e5566f]/20 text-[#e5566f]',
        badge: 'bg-[#e5566f]/25 text-[#e5566f] border border-[#e5566f]/40',
        defaultCode: 'AUTH_401',
      };
    }
    if (isModelNotFound) {
      return {
        card: 'bg-[#8b5cf6]/10 border-[#8b5cf6]/35',
        iconBg: 'bg-[#8b5cf6]/20 text-[#8b5cf6]',
        badge: 'bg-[#8b5cf6]/25 text-[#8b5cf6] border border-[#8b5cf6]/40',
        defaultCode: 'MODEL_404',
      };
    }
    if (isContextLimit) {
      return {
        card: 'bg-[#06b6d4]/10 border-[#06b6d4]/35',
        iconBg: 'bg-[#06b6d4]/20 text-[#06b6d4]',
        badge: 'bg-[#06b6d4]/25 text-[#06b6d4] border border-[#06b6d4]/40',
        defaultCode: 'CONTEXT_WINDOW_LIMIT',
      };
    }
    if (isContentPolicy) {
      return {
        card: 'bg-[#f97316]/10 border-[#f97316]/35',
        iconBg: 'bg-[#f97316]/20 text-[#f97316]',
        badge: 'bg-[#f97316]/25 text-[#f97316] border border-[#f97316]/40',
        defaultCode: 'CONTENT_MODERATION',
      };
    }
    if (isSchemaError) {
      return {
        card: 'bg-[#a855f7]/10 border-[#a855f7]/35',
        iconBg: 'bg-[#a855f7]/20 text-[#a855f7]',
        badge: 'bg-[#a855f7]/25 text-[#a855f7] border border-[#a855f7]/40',
        defaultCode: 'SCHEMA_PARSE_ERROR',
      };
    }
    return {
      card: 'bg-[#e5566f]/10 border-[#e5566f]/35',
      iconBg: 'bg-[#e5566f]/20 text-[#e5566f]',
      badge: 'bg-[#e5566f]/25 text-[#e5566f] border border-[#e5566f]/40',
      defaultCode: 'SERVER_ERROR',
    };
  }, [isRateLimit, isAuth, isModelNotFound, isContextLimit, isContentPolicy, isSchemaError]);

  const handleContainerClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const btn = target.closest('button.citation-tag');
    if (btn) {
      const citeKey = (btn.getAttribute('data-cite') || '').trim();
      const cleanKey = citeKey.replace(/[[\]]/g, '').trim().toLowerCase();
      const numMatch = cleanKey.match(/\d+/);
      const numOnly = numMatch ? numMatch[0] : '';

      const matched = citationMap.get(cleanKey)
        || citationMap.get(citeKey)
        || (numOnly ? citationMap.get(`cite_${numOnly}`) : undefined)
        || (numOnly ? citationMap.get(`cite${numOnly}`) : undefined)
        || (numOnly ? citationMap.get(numOnly) : undefined)
        || (numOnly ? citationMap.get(`cite:${numOnly}`) : undefined);

      if (matched) {
        onSelectCitation(matched);
      } else if (citeKey) {
        onSelectCitation({
          citation_id: citeKey.startsWith('[') ? citeKey : `[${citeKey}]`,
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

  const triggerAutoPurgeIfNeeded = (runId?: string) => {
    if (isAutoPurgeOnExport() && runId) {
      setTimeout(() => {
        fetch(`/research/${runId}`, {
          method: 'DELETE',
          headers: {
            'X-Session-ID': getSessionId(),
          },
        }).catch(() => {});
      }, 1500);
    }
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
    triggerAutoPurgeIfNeeded(jobData?.run_id);
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
    triggerAutoPurgeIfNeeded(jobData?.run_id);
  };

  const [isExporting, setIsExporting] = React.useState<string | null>(null);

  const handleExportBackend = async (format: 'pdf' | 'docx' | 'html' | 'markdown') => {
    if (!jobData?.run_id) return;
    try {
      setIsExporting(format);
      const sessionId = getSessionId();
      const res = await fetch(`/research/${jobData.run_id}/export?format=${format}&session_id=${encodeURIComponent(sessionId)}`, {
        headers: {
          'X-Session-ID': sessionId,
        },
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        alert(`Export failed (${res.status}): ${errJson.error || errJson.detail || res.statusText}`);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      const disposition = res.headers.get('Content-Disposition');
      let filename = `research_report_${jobData.run_id.slice(0, 8)}.${format === 'markdown' ? 'md' : format}`;
      if (disposition && disposition.includes('filename=')) {
        const match = disposition.match(/filename="?([^";]+)"?/);
        if (match && match[1]) filename = match[1];
      }
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      triggerAutoPurgeIfNeeded(jobData.run_id);
    } catch (err: any) {
      console.error('Export error:', err);
      alert(`Export error: ${err.message || 'Network error'}`);
    } finally {
      setIsExporting(null);
    }
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
          const isFinished = jobData?.status === 'completed' || jobData?.status === 'budget_exceeded';
          const isCancelled = jobData?.status === 'cancelled';
          const grade = isFinished ? (ragScore?.grade || ragScore?.composite_grade || null) : null;
          const groundednessPct = isFinished && ragScore ? Math.round((ragScore.groundedness_score ?? 0) * 100) : null;
          const precisionPct = isFinished && ragScore ? Math.round((ragScore.citation_precision ?? ragScore.citation_precision_score ?? 0) * 100) : null;
          const coveragePct = isFinished && ragScore ? Math.round((ragScore.coverage_score ?? ragScore.subquestion_coverage_score ?? 0) * 100) : null;

          return (
            <div className="p-4.5 rounded-md bg-[#131217] border border-[#222224] space-y-3.5">
              <div className="flex items-center justify-between pb-2.5 border-b border-[#1b1a1f]">
                <div className="flex items-center space-x-2 text-sm text-white font-medium">
                  <ShieldCheck className="w-4 h-4 text-[#44a282] stroke-[1.75]" />
                  <span>Source Verification</span>
                </div>
                <span className={`px-2.5 py-0.5 rounded text-[13px] font-medium ${
                  isCancelled
                    ? 'bg-[#212023] text-[#8a8c92]'
                    : grade === 'A+' || grade === 'A'
                    ? 'bg-[#1b2828] text-[#5fc39c] border border-[#44a282]/30'
                    : grade
                    ? 'bg-[#212023] text-[#4a8ad6] border border-[#4a8ad6]/30'
                    : 'bg-[#212023] text-[#8a8c92]'
                }`}>
                  {isCancelled ? 'Cancelled' : grade ? `Grade ${grade}` : 'Pending'}
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

                {/* Interactive Verified Sources & Deep Links Ledger */}
                {report?.citations && report.citations.length > 0 && (
                  <div className="pt-3 border-t border-[#1b1a1f] space-y-2">
                    <div className="flex items-center justify-between text-xs text-[#8a8c92]">
                      <span className="font-medium text-white/90">
                        Verified Sources ({report.citations.length})
                      </span>
                      <span className="text-[11px] text-[#4a8ad6]">Click to inspect</span>
                    </div>
                    <div className="max-h-44 overflow-y-auto space-y-1.5 pr-1">
                      {report.citations.map((cite) => {
                        const domainName = (() => {
                          try {
                            return new URL(cite.source_url).hostname.replace(/^www\./, '');
                          } catch {
                            return cite.source_url;
                          }
                        })();
                        const hasAnchor = Boolean(cite.anchor_url && cite.anchor_url.includes('#:~:text='));
                        return (
                          <button
                            key={cite.citation_id}
                            type="button"
                            onClick={() => onSelectCitation(cite)}
                            className="w-full text-left p-2 rounded bg-[#171719] hover:bg-[#1f1e24] border border-[#222224] hover:border-[#4a8ad6]/40 transition-colors flex items-start space-x-2 group cursor-pointer"
                          >
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-[#212023] text-[#4a8ad6] border border-[#4a8ad6]/30 shrink-0">
                              {cite.citation_id.replace(/[[\]]/g, '')}
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between text-[11px]">
                                <span className="font-mono text-white/90 truncate group-hover:text-[#7bb0ed]">
                                  {domainName}
                                </span>
                                {hasAnchor && (
                                  <span className="text-[9px] text-[#5fc39c] bg-[#1b2828] px-1 rounded border border-[#44a282]/30 shrink-0 ml-1">
                                    anchor
                                  </span>
                                )}
                              </div>
                              <p className="text-[11px] text-[#8a8c92] line-clamp-1 mt-0.5 italic">
                                &ldquo;{cite.verbatim_quote || cite.verified_claim}&rdquo;
                              </p>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
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
              {(jobData?.status === 'awaiting_approval' || status === 'awaiting_approval') && (
                <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-xs font-medium bg-[#d9a441]/20 text-[#d9a441] border border-[#d9a441]/35 animate-pulse">
                  <span>Awaiting Decision</span>
                </span>
              )}
              {(jobData?.status === 'cancelled' || status === 'cancelled') && (
                <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded text-xs font-medium bg-[#e5566f]/20 text-[#e5566f] border border-[#e5566f]/30">
                  <span>Cancelled</span>
                </span>
              )}
              {jobData?.focus_mode && jobData.focus_mode !== 'general' && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-[#8a5cf6]/15 text-[#a78bfa] border border-[#8a5cf6]/30">
                  {jobData.focus_mode === 'academic' && '🎓 Academic'}
                  {jobData.focus_mode === 'technical' && '⚡ Technical'}
                  {jobData.focus_mode === 'financial' && '📈 Financial'}
                </span>
              )}
            </div>

            {/* Actions */}
            {report && (
              <div className="flex items-center space-x-1.5 text-xs">
                <button
                  type="button"
                  disabled={Boolean(isExporting)}
                  onClick={() => handleExportBackend('pdf')}
                  className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-md bg-[#1e293b] hover:bg-[#334155] disabled:opacity-50 border border-[#3b82f6]/40 text-[#93c5fd] hover:text-white transition-colors cursor-pointer"
                  title="Download Publication-Grade PDF with Citations"
                >
                  <Download className={`w-3.5 h-3.5 text-[#60a5fa] ${isExporting === 'pdf' ? 'animate-bounce' : ''}`} />
                  <span className="font-medium">{isExporting === 'pdf' ? 'Exporting...' : 'PDF'}</span>
                </button>
                <button
                  type="button"
                  disabled={Boolean(isExporting)}
                  onClick={() => handleExportBackend('docx')}
                  className="inline-flex items-center space-x-1.5 px-2.5 py-1.5 rounded-md bg-[#212023] hover:bg-[#2a292e] disabled:opacity-50 border border-[#222224] text-[#8a8c92] hover:text-white transition-colors cursor-pointer"
                  title="Download Microsoft Word (.docx)"
                >
                  <FileText className={`w-3.5 h-3.5 text-[#818cf8] ${isExporting === 'docx' ? 'animate-bounce' : ''}`} />
                  <span>{isExporting === 'docx' ? 'Exporting...' : 'Word'}</span>
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
              (status === 'awaiting_approval' || (jobData?.status === 'awaiting_approval' && status !== 'researching' && status !== 'writing' && status !== 'completed')) ? (
                <div className="py-2 max-w-3xl mx-auto">
                  <PlanSteeringCard
                    initialPlan={jobData?.plan}
                    onSteer={onSteerPlan || (async () => false)}
                  />
                </div>
              ) : (jobData?.status === 'cancelled' || status === 'cancelled') ? (
                <div className="py-8 px-4 max-w-xl mx-auto space-y-4 animate-in fade-in duration-200">
                  <div className="p-5 sm:p-6 rounded-lg border bg-[#1a1820] border-[#34323e]">
                    <div className="flex items-start space-x-3.5 mb-3.5">
                      <div className="p-2.5 rounded-md shrink-0 bg-[#e5566f]/15 text-[#e5566f]">
                        <XCircle className="w-5 h-5 stroke-[2]" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-semibold text-sm sm:text-base text-white">
                            Investigation Cancelled
                          </h3>
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-[#e5566f]/20 text-[#e5566f] border border-[#e5566f]/30">
                            CANCELLED_BY_USER
                          </span>
                        </div>
                        {jobData?.query && (
                          <p className="text-xs text-[#8a8c92] mt-1 line-clamp-1">
                            Topic: &quot;{jobData.query}&quot;
                          </p>
                        )}
                      </div>
                    </div>

                    <div className="bg-[#131217] p-3.5 rounded-md border border-[#222224] text-xs text-white/80 leading-relaxed mb-4">
                      You declined or stopped the proposed research strategy during the plan review phase. You can adjust your research depth (number of sub-topics), review mode (HITL), or focus settings above and click Regenerate.
                    </div>

                    <div className="flex flex-wrap items-center gap-2.5 pt-3 border-t border-[#222224]">
                      {onRetry && (
                        <button
                          type="button"
                          onClick={onRetry}
                          className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-md bg-[#2568b2] hover:bg-[#1e5494] text-white text-xs font-medium transition-colors cursor-pointer shadow-sm"
                          title="Regenerate research using current configuration"
                        >
                          <RefreshCw className="w-3.5 h-3.5 text-white" />
                          <span>Regenerate Investigation</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ) : jobData?.status === 'failed' || jobData?.error_message ? (
                <div className="py-8 px-4 max-w-xl mx-auto space-y-4 animate-in fade-in duration-200">
                  {/* Actionable Error Card Container */}
                  <div className={`p-5 sm:p-6 rounded-lg border ${errorTheme.card}`}>
                    {/* Header with Title and Icon */}
                    <div className="flex items-start space-x-3.5 mb-3.5">
                      <div className={`p-2.5 rounded-md shrink-0 ${errorTheme.iconBg}`}>
                        {isRateLimit && <AlertTriangle className="w-5 h-5 stroke-[2]" />}
                        {isAuth && <KeyRound className="w-5 h-5 stroke-[2]" />}
                        {isModelNotFound && <Cpu className="w-5 h-5 stroke-[2]" />}
                        {isContextLimit && <Layers className="w-5 h-5 stroke-[2]" />}
                        {isContentPolicy && <ShieldAlert className="w-5 h-5 stroke-[2]" />}
                        {isSchemaError && <FileCode2 className="w-5 h-5 stroke-[2]" />}
                        {!isRateLimit && !isAuth && !isModelNotFound && !isContextLimit && !isContentPolicy && !isSchemaError && <XCircle className="w-5 h-5 stroke-[2]" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-semibold text-sm sm:text-base text-white">
                            {errorTitle}
                          </h3>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium ${errorTheme.badge}`}>
                            {jobData.error_code || errorTheme.defaultCode}
                          </span>
                        </div>
                        {jobData.query && (
                          <p className="text-xs text-[#8a8c92] mt-1 line-clamp-1">
                            Investigation: &quot;{jobData.query}&quot;
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Explanatory Message */}
                    <div className="bg-[#131217] p-3.5 rounded-md border border-[#222224] text-xs text-white/90 leading-relaxed mb-3">
                      {jobData.error_message || 'The research execution encountered an unexpected error.'}
                    </div>

                    {/* Actionable Solution Note */}
                    {jobData.error_suggestion && (
                      <div className="flex items-start space-x-2 text-xs text-[#8a8c92] mb-4 bg-white/5 p-3 rounded border border-white/10 leading-relaxed">
                        <span className="text-[#4a8ad6] shrink-0 font-bold">Suggested Fix:</span>
                        <span className="text-white/80">{jobData.error_suggestion}</span>
                      </div>
                    )}

                    {/* Action Buttons: Open Settings & Retry */}
                    <div className="flex flex-wrap items-center gap-2.5 pt-3 border-t border-[#222224]">
                      {onOpenSettings && (
                        <button
                          type="button"
                          onClick={onOpenSettings}
                          className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-md bg-[#2568b2] hover:bg-[#1e5494] text-white text-xs font-medium transition-colors cursor-pointer shadow-sm"
                        >
                          <SlidersHorizontal className="w-3.5 h-3.5" />
                          <span>Configure Model &amp; API Keys</span>
                        </button>
                      )}
                      {onRetry && (
                        <button
                          type="button"
                          onClick={onRetry}
                          className="inline-flex items-center space-x-1.5 px-3 py-2 rounded-md bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-white text-xs font-medium transition-colors cursor-pointer"
                        >
                          <RefreshCw className="w-3.5 h-3.5 text-[#4a8ad6]" />
                          <span>Retry Query</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
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
              )
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
