import React, { useState, useEffect } from 'react';
import { Compass, SlidersHorizontal, Activity } from 'lucide-react';

interface HeaderProps {
  tokens?: number;
  costUsd: number;
  timer: string;
  isDispatching: boolean;
  hasTrace: boolean;
  onOpenSettings: () => void;
  onOpenTrace: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  costUsd,
  timer,
  isDispatching,
  hasTrace,
  onOpenSettings,
  onOpenTrace,
}) => {
  const [isOnline, setIsOnline] = useState<boolean | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/health');
        if (res.ok) {
          const data = await res.json();
          setIsOnline(Boolean(data.redis_connected));
        } else {
          setIsOnline(false);
        }
      } catch {
        setIsOnline(false);
      }
    };
    check();
    const interval = setInterval(check, 25000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="h-18 border-b border-white/[0.08] bg-[#0c0e14]/90 backdrop-blur-md px-6 md:px-10 flex items-center justify-between sticky top-0 z-30">
      {/* Brand Identity */}
      <div className="flex items-center space-x-3.5">
        <div className="w-10 h-10 rounded-xl bg-blue-600/10 border border-blue-500/25 flex items-center justify-center text-blue-400 shadow-sm">
          <Compass className="w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center space-x-2.5">
            <h1 className="font-semibold text-base sm:text-lg tracking-tight text-white">
              AI Research Assistant
            </h1>
            <span className="inline-flex items-center space-x-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-white/[0.04] text-white/70 border border-white/[0.08]">
              <span className={`w-2 h-2 rounded-full ${isOnline ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              <span>{isOnline ? 'Ready' : 'Connecting'}</span>
            </span>
          </div>
          <p className="text-xs sm:text-sm text-white/50 hidden sm:block">
            In-depth web research, source verification, and structured reports
          </p>
        </div>
      </div>

      {/* Action Controls */}
      <div className="flex items-center space-x-3 sm:space-x-4">
        {/* Researching Timer */}
        {isDispatching && (
          <div className="flex items-center space-x-2 px-3.5 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/25 text-blue-300 font-mono text-sm">
            <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping" />
            <span>Researching: {timer}</span>
          </div>
        )}

        {/* Cost estimate */}
        <div className="hidden md:flex items-center space-x-2 px-3.5 py-2 rounded-lg bg-white/[0.03] border border-white/[0.08] text-sm text-white/70">
          <span>Est. Cost:</span>
          <span className="font-mono font-medium text-white">
            ${costUsd.toFixed(4)}
          </span>
        </div>

        {/* Activity & Step Details */}
        <button
          type="button"
          onClick={onOpenTrace}
          className={`inline-flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors cursor-pointer ${
            hasTrace
              ? 'bg-blue-500/10 border-blue-500/30 text-blue-300 hover:bg-blue-500/20'
              : 'bg-white/[0.03] border-white/[0.08] text-white/70 hover:text-white hover:bg-white/[0.06]'
          }`}
          title="View detailed execution steps, timings, and logs"
        >
          <Activity className="w-4 h-4" />
          <span className="hidden sm:inline">Activity Details</span>
        </button>

        {/* Settings */}
        <button
          type="button"
          onClick={onOpenSettings}
          className="inline-flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.08] text-white/80 hover:text-white transition-colors cursor-pointer"
          title="Configure AI models and optional API keys"
        >
          <SlidersHorizontal className="w-4 h-4" />
          <span>Settings</span>
        </button>
      </div>
    </header>
  );
};
