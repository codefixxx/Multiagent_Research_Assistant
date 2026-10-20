import React, { useState } from 'react';
import { Search, ArrowRight, Loader2 } from 'lucide-react';

interface CommandDeckProps {
  isDispatching: boolean;
  onDispatch: (
    query: string,
    subQuestionsCount: number,
    timeLimitSec: number,
    deepScrape: boolean
  ) => void;
}

const STARTERS = [
  { label: 'LanceDB vs Chroma', query: 'Compare LanceDB vs Chroma for local vector search in AI agents' },
  { label: 'WebAssembly vs Docker', query: 'WebAssembly vs Docker containers for edge computing in 2026' },
  { label: 'DeepSeek V3 vs Sonnet', query: 'Cost and latency trade-offs of DeepSeek V3 compared to Claude 3.5 Sonnet' }
];

export const CommandDeck: React.FC<CommandDeckProps> = ({
  isDispatching,
  onDispatch
}) => {
  const [query, setQuery] = useState('');
  const [depth, setDepth] = useState(2);
  const [timeLimit, setTimeLimit] = useState(120);
  const [deepScrape, setDeepScrape] = useState(true);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || isDispatching) return;
    onDispatch(query.trim(), depth, timeLimit, deepScrape);
  };

  return (
    <section className="w-full max-w-[1600px] mx-auto px-6 md:px-10 pt-6 pb-3">
      <form onSubmit={handleSubmit} className="space-y-3">
        {/* Main Search Input */}
        <div className="relative flex items-center rounded-md bg-[#131217] border border-[#222224] focus-within:border-[#4a8ad6] transition-colors">
          <div className="pl-5 text-[#8a8c92]">
            <Search className="w-5 h-5 stroke-[1.75]" />
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask anything to research (e.g., tech comparisons, architecture decisions, market facts)..."
            disabled={isDispatching}
            className="w-full bg-transparent px-4 py-3.5 text-sm sm:text-base text-white placeholder-[#8a8c92]/60 focus:outline-none disabled:opacity-50"
          />
          <div className="pr-3">
            <button
              type="submit"
              disabled={!query.trim() || isDispatching}
              className="inline-flex items-center space-x-2 px-5 py-2.5 rounded-md bg-[#2568b2] hover:bg-[#1e5494] text-white text-sm font-medium transition-colors disabled:bg-[#212023] disabled:text-[#a0a2a8] cursor-pointer disabled:cursor-not-allowed"
            >
              {isDispatching ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Researching...</span>
                </>
              ) : (
                <>
                  <span>Start Research</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </div>

        {/* Options & Starters */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-[#8a8c92]">
          {/* Controls */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Depth Selector */}
            <div className="flex items-center space-x-1.5 bg-[#131217] border border-[#222224] rounded-md px-3 py-1.5">
              <span className="text-[#8a8c92]">Depth:</span>
              <select
                value={depth}
                onChange={(e) => setDepth(Number(e.target.value))}
                disabled={isDispatching}
                className="bg-transparent text-white font-medium text-[13px] focus:outline-none cursor-pointer"
              >
                <option value={2} className="bg-[#131217] text-white">Standard (2 sub-topics)</option>
                <option value={3} className="bg-[#131217] text-white">Comprehensive (3 sub-topics)</option>
                <option value={4} className="bg-[#131217] text-white">Deep Dive (4 sub-topics)</option>
              </select>
            </div>

            {/* Time limit */}
            <div className="flex items-center space-x-1.5 bg-[#131217] border border-[#222224] rounded-md px-3 py-1.5">
              <span className="text-[#8a8c92]">Time:</span>
              <select
                value={timeLimit}
                onChange={(e) => setTimeLimit(Number(e.target.value))}
                disabled={isDispatching}
                className="bg-transparent text-white font-medium text-[13px] focus:outline-none cursor-pointer"
              >
                <option value={60} className="bg-[#131217] text-white">Quick (60s)</option>
                <option value={120} className="bg-[#131217] text-white">Standard (2 mins)</option>
                <option value={180} className="bg-[#131217] text-white">Thorough (3 mins)</option>
              </select>
            </div>

            {/* Read full web pages */}
            <label className="flex items-center space-x-2 bg-[#131217] border border-[#222224] rounded-md px-3 py-1.5 cursor-pointer hover:bg-[#212023] transition-colors">
              <input
                type="checkbox"
                checked={deepScrape}
                onChange={(e) => setDeepScrape(e.target.checked)}
                disabled={isDispatching}
                className="w-3.5 h-3.5 rounded border-[#222224] bg-transparent text-[#4a8ad6] focus:ring-0 cursor-pointer"
              />
              <span className="text-white/90 select-none text-[13px]">Read Full Web Pages</span>
            </label>
          </div>

          {/* Starters */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[#8a8c92] hidden lg:inline text-[13px]">
              Presets:
            </span>
            {STARTERS.map((s, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setQuery(s.query)}
                disabled={isDispatching}
                className="px-2.5 py-1 rounded-md text-[13px] bg-[#131217] hover:bg-[#212023] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors cursor-pointer"
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </form>
    </section>
  );
};
