import React, { useState } from 'react';
import { Search, ArrowRight, Loader2, Sparkles } from 'lucide-react';

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
    <section className="w-full max-w-[1600px] mx-auto px-6 md:px-10 pt-8 pb-4">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Main Search Input */}
        <div className="relative flex items-center rounded-2xl bg-[#12151c] border border-white/[0.12] shadow-xl focus-within:border-blue-500/70 focus-within:ring-3 focus-within:ring-blue-500/15 transition-all">
          <div className="pl-6 text-white/40">
            <Search className="w-6 h-6" />
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask anything to research (e.g., tech comparisons, architecture decisions, market facts)..."
            disabled={isDispatching}
            className="w-full bg-transparent px-5 py-5 text-base sm:text-lg text-white placeholder-white/35 focus:outline-none disabled:opacity-50"
          />
          <div className="pr-4">
            <button
              type="submit"
              disabled={!query.trim() || isDispatching}
              className="inline-flex items-center space-x-2.5 px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-sm sm:text-base font-medium transition-all disabled:opacity-40 disabled:hover:bg-blue-600 cursor-pointer disabled:cursor-not-allowed shadow-md hover:shadow-blue-500/20"
            >
              {isDispatching ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  <span>Researching...</span>
                </>
              ) : (
                <>
                  <span>Start Research</span>
                  <ArrowRight className="w-5 h-5" />
                </>
              )}
            </button>
          </div>
        </div>

        {/* Options & Quick Starters */}
        <div className="flex flex-wrap items-center justify-between gap-4 text-sm text-white/70">
          {/* Controls */}
          <div className="flex flex-wrap items-center gap-3">
            {/* Depth Selector */}
            <div className="flex items-center space-x-2 bg-white/[0.03] border border-white/[0.08] rounded-lg px-3.5 py-2">
              <span className="text-white/50 text-sm">Depth:</span>
              <select
                value={depth}
                onChange={(e) => setDepth(Number(e.target.value))}
                disabled={isDispatching}
                className="bg-transparent text-white font-medium text-sm focus:outline-none cursor-pointer"
              >
                <option value={2} className="bg-[#12151c] text-white">Standard (2 sub-topics)</option>
                <option value={3} className="bg-[#12151c] text-white">Comprehensive (3 sub-topics)</option>
                <option value={4} className="bg-[#12151c] text-white">Deep Dive (4 sub-topics)</option>
              </select>
            </div>

            {/* Time limit */}
            <div className="flex items-center space-x-2 bg-white/[0.03] border border-white/[0.08] rounded-lg px-3.5 py-2">
              <span className="text-white/50 text-sm">Time:</span>
              <select
                value={timeLimit}
                onChange={(e) => setTimeLimit(Number(e.target.value))}
                disabled={isDispatching}
                className="bg-transparent text-white font-medium text-sm focus:outline-none cursor-pointer"
              >
                <option value={60} className="bg-[#12151c] text-white">Quick (60s)</option>
                <option value={120} className="bg-[#12151c] text-white">Standard (2 mins)</option>
                <option value={180} className="bg-[#12151c] text-white">Thorough (3 mins)</option>
              </select>
            </div>

            {/* Read full web pages */}
            <label className="flex items-center space-x-2.5 bg-white/[0.03] border border-white/[0.08] rounded-lg px-3.5 py-2 cursor-pointer hover:bg-white/[0.05] transition-colors">
              <input
                type="checkbox"
                checked={deepScrape}
                onChange={(e) => setDeepScrape(e.target.checked)}
                disabled={isDispatching}
                className="w-4 h-4 rounded border-white/20 bg-white/5 text-blue-500 focus:ring-0 cursor-pointer"
              />
              <span className="text-white/80 select-none text-sm">Read Full Web Pages</span>
            </label>
          </div>

          {/* Quick Starters */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-white/40 flex items-center space-x-1.5 hidden lg:inline-flex text-sm">
              <Sparkles className="w-4 h-4 text-blue-400" />
              <span>Examples:</span>
            </span>
            {STARTERS.map((s, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setQuery(s.query)}
                disabled={isDispatching}
                className="px-3.5 py-1.5 rounded-lg text-sm bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] text-white/70 hover:text-white transition-colors cursor-pointer"
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
