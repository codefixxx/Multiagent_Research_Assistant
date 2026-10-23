import React, { useState, useEffect } from 'react';
import { SlidersHorizontal, Activity, Clock } from 'lucide-react';

interface HeaderProps {
  tokens?: number;
  costUsd: number;
  timer: string;
  isDispatching: boolean;
  hasTrace: boolean;
  onOpenSettings: () => void;
  onOpenTrace: () => void;
  onOpenHistory: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  costUsd,
  timer,
  isDispatching,
  hasTrace,
  onOpenSettings,
  onOpenTrace,
  onOpenHistory,
}) => {
  const [isOnline, setIsOnline] = useState<boolean | null>(null);
  const [requireByok, setRequireByok] = useState<boolean>(false);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/health');
        if (res.ok) {
          const data = await res.json();
          setIsOnline(Boolean(data.redis_connected));
          if (data.require_byok) {
            setRequireByok(true);
          }
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
    <header className="h-16 border-b border-[#222224] bg-[#131217] px-6 lg:px-10 flex items-center justify-between sticky top-0 z-30">
      {/* Brand Identity */}
      <div className="flex items-center space-x-2.5 sm:space-x-3 shrink-0">
        <div className="flex items-center justify-center shrink-0 w-6 h-6" aria-hidden="true">
          <svg viewBox="0 0 128 128" fill="none" className="w-5 h-5">
            <g stroke="#6366F1" strokeWidth="4" strokeLinecap="round">
              <path d="M64 52V30M49 65L29 85M79 65L99 85" />
            </g>
            <g fill="#6366F1">
              <circle cx="64" cy="22" r="10" />
              <circle cx="23" cy="91" r="10" />
              <circle cx="105" cy="91" r="10" />
            </g>
            <rect x="43" y="48" width="42" height="38" rx="12" fill="#EEF2FF" stroke="#6366F1" strokeWidth="3" />
            <path d="M53 62H75M53 71H69" stroke="#6366F1" strokeWidth="3" strokeLinecap="round" />
          </svg>
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="font-semibold text-sm sm:text-base tracking-tight text-white whitespace-nowrap">
              AI Research Assistant
            </h1>
            <span className="inline-flex items-center space-x-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-[#212023] text-[#8a8c92] border border-[#222224] shrink-0">
              <span className={`w-1.5 h-1.5 rounded-full ${isOnline ? 'bg-[#44a282]' : 'bg-[#d9a441]'}`} />
              <span>{isOnline ? 'Ready' : 'Connecting'}</span>
            </span>
          </div>
          <p className="text-[13px] text-[#8a8c92] hidden sm:block">
            In-depth web research, source verification, and structured reports
          </p>
        </div>
      </div>

      {/* Action Controls */}
      <div className="flex items-center space-x-2 sm:space-x-3">
        {/* Researching Timer */}
        {isDispatching && (
          <div className="flex items-center space-x-2 px-3 py-1.5 rounded-md bg-[#212023] border border-[#4a8ad6]/30 text-[#4a8ad6] text-[13px] font-medium tabular">
            <span className="w-1.5 h-1.5 rounded-full bg-[#4a8ad6]" />
            <span>Researching: {timer}</span>
          </div>
        )}

        {/* Cost estimate - shown on large screens */}
        <div className="hidden lg:flex items-center space-x-2 px-3 py-1.5 rounded-md bg-[#212023] border border-[#222224] text-[13px] text-[#8a8c92]">
          <span>Est. Cost:</span>
          <span className="font-medium text-white tabular">
            ${costUsd.toFixed(4)}
          </span>
        </div>

        {/* History / Library */}
        <button
          type="button"
          onClick={onOpenHistory}
          className="inline-flex items-center space-x-2 px-3 py-1.5 rounded-md text-[13px] font-medium bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors cursor-pointer"
          title="Browse recent research runs and saved dossiers"
        >
          <Clock className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">History</span>
        </button>

        {/* Activity & Step Details */}
        <button
          type="button"
          onClick={onOpenTrace}
          className={`inline-flex items-center space-x-2 px-3.5 py-1.5 rounded-md text-[13px] font-medium border transition-colors cursor-pointer ${
            hasTrace
              ? 'bg-[#212023] border-[#4a8ad6]/40 text-[#4a8ad6] hover:bg-[#2a292e]'
              : 'bg-[#212023] border-[#222224] text-[#8a8c92] hover:text-white hover:bg-[#2a292e]'
          }`}
          title="View detailed execution steps, timings, and logs"
        >
          <Activity className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Activity Details</span>
        </button>

        {/* Settings */}
        <button
          type="button"
          onClick={onOpenSettings}
          aria-label="Settings"
          className="inline-flex items-center space-x-1.5 sm:space-x-2 px-3 py-1.5 rounded-md text-[13px] font-medium bg-[#212023] hover:bg-[#2a292e] border border-[#222224] text-[#8a8c92] hover:text-white transition-colors cursor-pointer"
          title="Configure AI models and optional API keys"
        >
          <SlidersHorizontal className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Settings</span>
          {requireByok && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-[#d9a441]/10 text-[#d9a441] border border-[#d9a441]/30">
              BYOK
            </span>
          )}
        </button>
      </div>
    </header>
  );
};
