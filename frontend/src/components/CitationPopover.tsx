import React from 'react';
import type { Citation } from '../types';
import { X, ExternalLink, ShieldCheck } from 'lucide-react';

interface CitationPopoverProps {
  citation: Citation | null;
  onClose: () => void;
}

export const CitationPopover: React.FC<CitationPopoverProps> = ({
  citation,
  onClose
}) => {
  if (!citation) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75">
      <div className="w-full max-w-lg bg-[#131217] border border-[#222224] rounded-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="px-5 py-3.5 border-b border-[#222224] flex items-center justify-between bg-[#171719]">
          <div className="flex items-center space-x-2.5">
            <ShieldCheck className="w-4 h-4 text-[#44a282] stroke-[1.75]" />
            <span className="text-xs font-semibold text-white tabular">
              [{citation.citation_id.replace(/[\[\]]/g, '')}]
            </span>
            <span className="text-xs text-[#5fc39c] bg-[#1b2828] px-2 py-0.5 rounded border border-[#44a282]/30 font-medium">
              Verified Source
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-[#8a8c92] hover:text-white transition-colors p-1 rounded hover:bg-white/5 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4 text-xs">
          <div>
            <div className="text-xs font-medium text-[#8a8c92] mb-1.5">
              Verified Finding
            </div>
            <div className="text-white/90 bg-[#171719] border border-[#222224] p-3 rounded-md leading-relaxed text-xs">
              "{citation.verified_claim || 'Evidence corroborated from source retrieval.'}"
            </div>
          </div>

          <div>
            <div className="text-xs font-medium text-[#8a8c92] mb-1.5">
              Original Source Web Link
            </div>
            <a
              href={citation.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center space-x-1.5 text-[#4a8ad6] hover:text-[#7bb0ed] break-all underline decoration-[#4a8ad6]/30 underline-offset-2 hover:decoration-[#4a8ad6] text-xs"
            >
              <span>{citation.source_url}</span>
              <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-[#171719] border-t border-[#222224] flex justify-end">
          <button
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
