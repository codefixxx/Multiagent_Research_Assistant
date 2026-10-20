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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs">
      <div className="w-full max-w-lg bg-[#13151b] border border-white/[0.12] rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="px-5 py-4 border-b border-white/[0.08] flex items-center justify-between bg-white/[0.02]">
          <div className="flex items-center space-x-2.5">
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
            <span className="font-mono text-sm font-semibold text-white">
              [{citation.citation_id.replace(/[\[\]]/g, '')}]
            </span>
            <span className="text-xs text-emerald-400/90 bg-emerald-500/10 px-2.5 py-0.5 rounded-full border border-emerald-500/20 font-medium">
              Verified Source
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-white/40 hover:text-white transition-colors p-1.5 rounded-lg hover:bg-white/5 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4 text-sm">
          <div>
            <div className="text-xs font-semibold text-white/50 mb-1.5 uppercase tracking-wider">
              Verified Finding
            </div>
            <div className="text-white/90 bg-white/[0.02] border border-white/[0.06] p-3.5 rounded-xl leading-relaxed text-sm">
              "{citation.verified_claim || 'Evidence corroborated from source retrieval.'}"
            </div>
          </div>

          <div>
            <div className="text-xs font-semibold text-white/50 mb-1.5 uppercase tracking-wider">
              Original Source Web Link
            </div>
            <a
              href={citation.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center space-x-2 text-blue-400 hover:text-blue-300 break-all underline decoration-blue-500/30 underline-offset-2 hover:decoration-blue-400 text-sm"
            >
              <span>{citation.source_url}</span>
              <ExternalLink className="w-3.5 h-3.5 shrink-0" />
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3.5 bg-white/[0.01] border-t border-white/[0.06] flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-white/[0.05] hover:bg-white/[0.1] text-white/80 hover:text-white text-sm transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
