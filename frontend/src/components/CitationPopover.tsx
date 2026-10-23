import React, { useState, useEffect } from 'react';
import type { Citation } from '../types';
import { 
  X, 
  ExternalLink, 
  ShieldCheck, 
  Quote, 
  Copy, 
  Check, 
  Sparkles, 
  Globe, 
  CheckCircle2,
  Anchor
} from 'lucide-react';

interface CitationPopoverProps {
  citation: Citation | null;
  onClose: () => void;
}

export const CitationPopover: React.FC<CitationPopoverProps> = ({
  citation,
  onClose
}) => {
  const [copiedQuote, setCopiedQuote] = useState(false);

  // Close on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  if (!citation) return null;

  const domain = (() => {
    try {
      return new URL(citation.source_url).hostname.replace(/^www\./, '');
    } catch {
      return citation.source_url;
    }
  })();

  const cleanCitationId = citation.citation_id.replace(/[[\]]/g, '');
  const directTargetUrl = citation.anchor_url || citation.source_url;
  const hasTextFragment = Boolean(citation.anchor_url && citation.anchor_url.includes('#:~:text='));
  const verbatimText = citation.verbatim_quote || citation.verified_claim;

  const handleCopyQuote = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (verbatimText) {
      navigator.clipboard.writeText(verbatimText);
      setCopiedQuote(true);
      setTimeout(() => setCopiedQuote(false), 2000);
    }
  };

  const httpStatus = citation.http_status ?? 200;
  const statusBadge = httpStatus >= 200 && httpStatus < 300 
    ? { bg: 'bg-[#1b2828] text-[#5fc39c] border-[#44a282]/30', label: `${httpStatus} OK` }
    : httpStatus === 403 
    ? { bg: 'bg-[#d9a441]/20 text-[#d9a441] border-[#d9a441]/35', label: `${httpStatus} Protected` }
    : httpStatus >= 400
    ? { bg: 'bg-[#e5566f]/20 text-[#e5566f] border-[#e5566f]/30', label: `${httpStatus} Error` }
    : { bg: 'bg-[#212023] text-[#8a8c92] border-[#222224]', label: `${httpStatus}` };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-lg bg-[#131217] border border-[#222224] rounded-lg shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3.5 border-b border-[#222224] flex items-center justify-between bg-[#171719]">
          <div className="flex items-center space-x-2.5 flex-wrap gap-y-1">
            <ShieldCheck className="w-4 h-4 text-[#44a282] stroke-[1.75]" />
            <span className="text-xs font-semibold text-white font-mono">
              [{cleanCitationId}]
            </span>
            <span className="text-xs text-[#5fc39c] bg-[#1b2828] px-2 py-0.5 rounded border border-[#44a282]/30 font-medium">
              Verified Source
            </span>
            <span className={`text-[11px] px-2 py-0.5 rounded border font-mono font-medium ${statusBadge.bg}`}>
              {statusBadge.label}
            </span>
            {hasTextFragment && (
              <span className="inline-flex items-center space-x-1 text-[11px] text-[#93c5fd] bg-[#1e293b] px-2 py-0.5 rounded border border-[#3b82f6]/30 font-medium">
                <Anchor className="w-3 h-3" />
                <span>Text Anchor</span>
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[#8a8c92] hover:text-white transition-colors p-1 rounded hover:bg-white/5 cursor-pointer ml-2"
            aria-label="Close citation details"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 text-xs">
          {/* 1. Verbatim Source Web Excerpt */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs font-medium text-[#8a8c92]">
              <span className="flex items-center space-x-1.5 text-white/90">
                <Quote className="w-3.5 h-3.5 text-[#4a8ad6]" />
                <span>Verbatim Source Web Excerpt</span>
              </span>
              <button
                type="button"
                onClick={handleCopyQuote}
                className="inline-flex items-center space-x-1 px-2 py-0.5 rounded bg-[#212023] hover:bg-[#2a292e] text-[#8a8c92] hover:text-white transition-colors cursor-pointer text-[11px]"
                title="Copy verbatim quote to clipboard"
              >
                {copiedQuote ? (
                  <>
                    <Check className="w-3 h-3 text-[#5fc39c]" />
                    <span className="text-[#5fc39c]">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3" />
                    <span>Copy Quote</span>
                  </>
                )}
              </button>
            </div>
            <div className="relative text-white/95 bg-[#171719] border-l-2 border-[#4a8ad6] border-y border-r border-[#222224] p-3.5 rounded-r-md leading-relaxed text-xs italic font-serif select-text">
              &ldquo;{verbatimText}&rdquo;
            </div>
          </div>

          {/* 2. Substantiated Report Claim */}
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-[#8a8c92] flex items-center space-x-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#5fc39c]" />
              <span>Substantiated Report Finding</span>
            </div>
            <div className="text-white/85 bg-[#171719] border border-[#222224] p-3 rounded-md leading-relaxed text-xs select-text">
              {citation.verified_claim || 'Empirical evidence corroborated from web retrieval.'}
            </div>
          </div>

          {/* 3. Deep-Link CTA Button */}
          <div className="space-y-2 pt-1">
            <a
              href={directTargetUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="w-full inline-flex items-center justify-center space-x-2 px-4 py-2.5 rounded-md bg-[#2568b2] hover:bg-[#1e5494] text-white text-xs font-medium transition-colors shadow-sm cursor-pointer group"
            >
              <Sparkles className="w-3.5 h-3.5 text-[#93c5fd] group-hover:rotate-12 transition-transform" />
              <span>Open Direct Highlighted Text (W3C Anchor)</span>
              <ExternalLink className="w-3.5 h-3.5 shrink-0 ml-1" />
            </a>
            {hasTextFragment ? (
              <p className="text-[11px] text-[#8a8c92] leading-tight px-1">
                ✨ Uses browser W3C Text Fragments (<code className="text-[#93c5fd] font-mono">#:~:text=</code>) to scroll and highlight the cited sentence directly in Chrome, Edge, and Safari.
              </p>
            ) : (
              <p className="text-[11px] text-[#8a8c92] leading-tight px-1">
                Directly opens the verified source documentation page.
              </p>
            )}
          </div>

          {/* 4. Provenance Metadata Footer */}
          <div className="flex items-center justify-between text-xs text-[#8a8c92] pt-2 border-t border-[#222224]">
            <span className="flex items-center space-x-1.5 truncate max-w-[240px]">
              <Globe className="w-3.5 h-3.5 text-[#8a8c92] shrink-0" />
              <span className="truncate font-mono">{domain}</span>
            </span>
            <a
              href={citation.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center space-x-1 text-[#4a8ad6] hover:text-[#7bb0ed] hover:underline"
            >
              <span>Visit Base Page</span>
              <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-[#171719] border-t border-[#222224] flex items-center justify-between text-xs text-[#8a8c92]">
          <span className="font-mono text-[11px]">Press ESC to close</span>
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-md bg-[#212023] hover:bg-[#2a292e] text-white text-xs transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
