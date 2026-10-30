import React, { useState, useEffect } from 'react';
import type { ModelMatrix, ApiKeys } from '../types';
import {
  X,
  Sliders,
  Key,
  Zap,
  Brain,
  Eye,
  EyeOff,
  Save,
  RotateCcw,
  ShieldCheck,
  Trash2,
  Copy,
  Check,
} from 'lucide-react';
import {
  getSessionId,
  isAutoPurgeOnExport,
  setAutoPurgeOnExport as saveAutoPurgeOnExport,
  isPurgeOnClose,
  setPurgeOnClose as savePurgeOnClose,
  purgeEntireSession,
} from '../utils/session';

interface SettingsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (matrix: ModelMatrix, keys: ApiKeys) => void;
  requireByok?: boolean;
  onSessionPurged?: () => void;
}

const DEFAULT_MATRIX: ModelMatrix = {
  planner: 'gemini-3.5-flash-lite',
  researcher: 'gemini-3.5-flash-lite',
  reviewer: 'gemini-3.5-flash-lite',
  writer: 'gemini-3.5-flash-lite',
};

export const SettingsDrawer: React.FC<SettingsDrawerProps> = ({
  isOpen,
  onClose,
  onSave,
  requireByok = false,
  onSessionPurged,
}) => {
  const [matrix, setMatrix] = useState<ModelMatrix>(DEFAULT_MATRIX);
  const [keys, setKeys] = useState<ApiKeys>({});
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});
  const [autoPurgeExport, setAutoPurgeExport] = useState(false);
  const [purgeClose, setPurgeClose] = useState(false);
  const [copiedSessionId, setCopiedSessionId] = useState(false);
  const [isPurging, setIsPurging] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState('');

  useEffect(() => {
    try {
      const savedMatrix = localStorage.getItem('multiagent_model_matrix');
      if (savedMatrix) setMatrix(JSON.parse(savedMatrix));
      // BYOK keys: use ephemeral sessionStorage and migrate away from localStorage
      const savedKeys =
        sessionStorage.getItem('multiagent_byok_keys') || localStorage.getItem('multiagent_byok_keys');
      if (savedKeys) {
        setKeys(JSON.parse(savedKeys));
        sessionStorage.setItem('multiagent_byok_keys', savedKeys);
        localStorage.removeItem('multiagent_byok_keys');
      }
      setAutoPurgeExport(isAutoPurgeOnExport());
      setPurgeClose(isPurgeOnClose());
      setCurrentSessionId(getSessionId());
    } catch {}
  }, [isOpen]);

  const toggleShowKey = (k: string) => {
    setShowKey(prev => ({ ...prev, [k]: !prev[k] }));
  };

  const handleApplyPreset = (type: 'fast' | 'quality') => {
    if (type === 'fast') {
      setMatrix({
        planner: 'gemini-3.5-flash-lite',
        researcher: 'gemini-3.5-flash-lite',
        reviewer: 'gemini-3.5-flash-lite',
        writer: 'gemini-3.5-flash-lite',
      });
    } else {
      setMatrix({
        planner: 'gpt-4o-mini',
        researcher: 'gemini-3.5-flash-lite',
        reviewer: 'gemini-3.5-flash-lite',
        writer: 'claude-3-5-sonnet-20241022',
      });
    }
  };

  const handleSave = () => {
    try {
      localStorage.setItem('multiagent_model_matrix', JSON.stringify(matrix));
      sessionStorage.setItem('multiagent_byok_keys', JSON.stringify(keys));
      localStorage.removeItem('multiagent_byok_keys');
      saveAutoPurgeOnExport(autoPurgeExport);
      savePurgeOnClose(purgeClose);
    } catch {}
    onSave(matrix, keys);
    onClose();
  };

  const handleCopySessionId = () => {
    if (!currentSessionId) return;
    navigator.clipboard.writeText(currentSessionId);
    setCopiedSessionId(true);
    setTimeout(() => setCopiedSessionId(false), 2000);
  };

  const handlePurgeAllData = async () => {
    if (!window.confirm("Immediately purge all research runs, logs, and checkpoints from this ephemeral session?")) {
      return;
    }
    setIsPurging(true);
    try {
      await purgeEntireSession();
      setKeys({});
      setCurrentSessionId(getSessionId());
      if (onSessionPurged) onSessionPurged();
      onSave(matrix, {});
    } finally {
      setIsPurging(false);
      onClose();
    }
  };

  const handleReset = () => {
    setMatrix(DEFAULT_MATRIX);
    setKeys({});
    try {
      localStorage.removeItem('multiagent_model_matrix');
      sessionStorage.removeItem('multiagent_byok_keys');
      localStorage.removeItem('multiagent_byok_keys');
    } catch {}
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/75 flex justify-end">
      <div className="w-full max-w-lg bg-[#131217] border-l border-[#222224] h-full flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="px-6 py-4.5 border-b border-[#222224] flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <Sliders className="w-4 h-4 text-[#4a8ad6] stroke-[1.75]" />
            <h3 className="font-semibold text-sm text-white">Settings & AI Models</h3>
          </div>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="text-[#8a8c92] hover:text-white p-1 rounded hover:bg-white/5 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5 text-xs">
          {/* Quick Presets */}
          <div className="space-y-2">
            <div className="text-xs font-medium text-[#8a8c92]">
              Quick Presets
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              <button
                type="button"
                onClick={() => handleApplyPreset('fast')}
                className="flex items-center space-x-2 p-2.5 rounded-md bg-[#171719] hover:bg-[#212023] border border-[#222224] text-white transition-colors cursor-pointer text-xs font-medium"
              >
                <Zap className="w-3.5 h-3.5 text-[#d9a441]" />
                <span>Fast & Efficient</span>
              </button>
              <button
                type="button"
                onClick={() => handleApplyPreset('quality')}
                className="flex items-center space-x-2 p-2.5 rounded-md bg-[#171719] hover:bg-[#212023] border border-[#222224] text-white transition-colors cursor-pointer text-xs font-medium"
              >
                <Brain className="w-3.5 h-3.5 text-[#4a8ad6]" />
                <span>Deep Synthesis</span>
              </button>
            </div>
          </div>

          {/* Model Selection */}
          <div className="space-y-3">
            <div className="text-xs font-medium text-[#8a8c92]">
              AI Model Selection
            </div>

            {/* Planner */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">1. Strategy & Planning</label>
              <select
                value={matrix.planner}
                onChange={(e) => setMatrix({ ...matrix, planner: e.target.value })}
                className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-2 text-white text-xs focus:outline-none focus:border-[#4a8ad6] cursor-pointer"
              >
                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="claude-3-5-haiku-20241022">Claude 3.5 Haiku</option>
              </select>
            </div>

            {/* Researcher */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">2. Web Research & Gathering</label>
              <select
                value={matrix.researcher}
                onChange={(e) => setMatrix({ ...matrix, researcher: e.target.value })}
                className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-2 text-white text-xs focus:outline-none focus:border-[#4a8ad6] cursor-pointer"
              >
                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="llama-3.3-70b-versatile">Groq / LLaMA 3.3 70B</option>
              </select>
            </div>

            {/* Reviewer */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">3. Fact & Quality Reviewer</label>
              <select
                value={matrix.reviewer}
                onChange={(e) => setMatrix({ ...matrix, reviewer: e.target.value })}
                className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-2 text-white text-xs focus:outline-none focus:border-[#4a8ad6] cursor-pointer"
              >
                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
              </select>
            </div>

            {/* Writer */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">4. Report Writing</label>
              <select
                value={matrix.writer}
                onChange={(e) => setMatrix({ ...matrix, writer: e.target.value })}
                className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-2 text-white text-xs focus:outline-none focus:border-[#4a8ad6] cursor-pointer"
              >
                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
                <option value="gpt-4o">GPT-4o</option>
                <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
              </select>
            </div>
          </div>

          {/* Optional / BYOK API Keys */}
          <div className="space-y-3 pt-3 border-t border-[#1b1a1f]">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-1.5 text-xs font-medium text-[#8a8c92]">
                <Key className="w-3.5 h-3.5 stroke-[1.75]" />
                <span>API Keys (Bring Your Own Key)</span>
              </div>
              {requireByok && (
                <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-[#d9a441]/10 text-[#d9a441] border border-[#d9a441]/30">
                  BYOK Required
                </span>
              )}
            </div>
            <div className="p-3 rounded-md bg-[#171719] border border-[#222224] text-[11px] leading-relaxed text-[#8a8c92] space-y-1.5">
              <p>
                <strong className="text-white">Ephemeral Session Protection:</strong> Your API keys are held purely in temporary session storage (never written to permanent disk), encrypted in transit over AES-256-GCM, and automatically purged when you close the tab.
              </p>
              <p>
                Need a free Gemini key? Grab one instantly at{' '}
                <a
                  href="https://aistudio.google.com/app/apikey"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[#4a8ad6] hover:underline font-medium inline-flex items-center gap-0.5"
                >
                  Google AI Studio ↗
                </a>
              </p>
            </div>

            {/* Gemini */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-[#8a8c92] text-xs flex items-center gap-1.5">
                  <span>Google Gemini API Key</span>
                  {requireByok && <span className="text-[#d9a441] text-[10px] font-medium">(Required)</span>}
                </label>
                <a
                  href="https://aistudio.google.com/app/apikey"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] text-[#4a8ad6] hover:underline"
                >
                  Get free key ↗
                </a>
              </div>
              <div className="relative flex items-center">
                <input
                  type={showKey.gemini ? 'text' : 'password'}
                  value={keys.gemini || ''}
                  onChange={(e) => setKeys({ ...keys, gemini: e.target.value.trim() })}
                  placeholder="AIzaSy... (Paste Gemini key)"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-lpignore="true"
                  data-1p-ignore="true"
                  className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-1.5 pr-8 text-white focus:outline-none text-xs tabular focus:border-[#4a8ad6]"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey('gemini')}
                  className="absolute right-2 text-[#8a8c92] hover:text-white"
                >
                  {showKey.gemini ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* OpenAI */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">OpenAI API Key</label>
              <div className="relative flex items-center">
                <input
                  type={showKey.openai ? 'text' : 'password'}
                  value={keys.openai || ''}
                  onChange={(e) => setKeys({ ...keys, openai: e.target.value.trim() })}
                  placeholder="sk-... (for GPT models)"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-lpignore="true"
                  data-1p-ignore="true"
                  className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-1.5 pr-8 text-white focus:outline-none text-xs tabular"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey('openai')}
                  className="absolute right-2 text-[#8a8c92] hover:text-white"
                >
                  {showKey.openai ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Anthropic */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">Anthropic API Key</label>
              <div className="relative flex items-center">
                <input
                  type={showKey.anthropic ? 'text' : 'password'}
                  value={keys.anthropic || ''}
                  onChange={(e) => setKeys({ ...keys, anthropic: e.target.value.trim() })}
                  placeholder="sk-ant-... (for Claude models)"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-lpignore="true"
                  data-1p-ignore="true"
                  className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-1.5 pr-8 text-white focus:outline-none text-xs tabular"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey('anthropic')}
                  className="absolute right-2 text-[#8a8c92] hover:text-white"
                >
                  {showKey.anthropic ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Groq Cloud */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">Groq Cloud API Key</label>
              <div className="relative flex items-center">
                <input
                  type={showKey.groq ? 'text' : 'password'}
                  value={keys.groq || ''}
                  onChange={(e) => setKeys({ ...keys, groq: e.target.value.trim() })}
                  placeholder="gsk_... (for fast Llama models)"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-lpignore="true"
                  data-1p-ignore="true"
                  className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-1.5 pr-8 text-white focus:outline-none text-xs tabular"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey('groq')}
                  className="absolute right-2 text-[#8a8c92] hover:text-white"
                >
                  {showKey.groq ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            {/* Tavily Search */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">Tavily Search API Key (Optional)</label>
              <div className="relative flex items-center">
                <input
                  type={showKey.tavily ? 'text' : 'password'}
                  value={keys.tavily || ''}
                  onChange={(e) => setKeys({ ...keys, tavily: e.target.value.trim() })}
                  placeholder="tvly-... (falls back to server key if omitted)"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-lpignore="true"
                  data-1p-ignore="true"
                  className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-1.5 pr-8 text-white focus:outline-none text-xs tabular"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey('tavily')}
                  className="absolute right-2 text-[#8a8c92] hover:text-white"
                >
                  {showKey.tavily ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
          </div>

          {/* Search & Forget Ephemeral Policy */}
          <div className="space-y-3 pt-3 border-t border-[#222224]">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2 text-white font-medium text-xs">
                <ShieldCheck className="w-3.5 h-3.5 text-[#30a46c]" />
                <span>Search & Forget Ephemeral Policy</span>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-[#30a46c]/10 text-[#30a46c] border border-[#30a46c]/30">
                Isolated
              </span>
            </div>

            <div className="p-3 rounded-md bg-[#171719] border border-[#222224] text-[11px] space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-[#8a8c92]">
                  Session Token:
                  <span className="ml-1.5 font-mono text-white text-[10px]">
                    {currentSessionId ? `${currentSessionId.substring(0, 16)}...` : 'Generating...'}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleCopySessionId}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-[#212023] hover:bg-[#2a292e] text-[#8a8c92] hover:text-white transition-colors cursor-pointer text-[10px]"
                >
                  {copiedSessionId ? (
                    <>
                      <Check className="w-3 h-3 text-[#30a46c]" />
                      <span>Copied</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3 h-3" />
                      <span>Copy ID</span>
                    </>
                  )}
                </button>
              </div>

              {/* Auto Purge on Export Option */}
              <label className="flex items-start gap-2.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={autoPurgeExport}
                  onChange={(e) => setAutoPurgeExport(e.target.checked)}
                  className="mt-0.5 rounded border-[#333338] bg-[#171719] text-[#4a8ad6] focus:ring-0 focus:ring-offset-0 cursor-pointer"
                />
                <div className="text-[11px] leading-snug">
                  <span className="text-white font-medium">Auto-purge run on export</span>
                  <p className="text-[#8a8c92] text-[10px] mt-0.5">
                    Instantly erase server trace, checkpoints, and findings as soon as you download the report.
                  </p>
                </div>
              </label>

              {/* Purge on Tab Close Option */}
              <label className="flex items-start gap-2.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={purgeClose}
                  onChange={(e) => setPurgeClose(e.target.checked)}
                  className="mt-0.5 rounded border-[#333338] bg-[#171719] text-[#4a8ad6] focus:ring-0 focus:ring-offset-0 cursor-pointer"
                />
                <div className="text-[11px] leading-snug">
                  <span className="text-white font-medium">Purge server state on tab close</span>
                  <p className="text-[#8a8c92] text-[10px] mt-0.5">
                    Sends an eviction beacon to clear all session runs from Redis when closing this tab.
                  </p>
                </div>
              </label>

              {/* Manual Purge Session Button */}
              <div className="pt-2 border-t border-[#222224] flex items-center justify-between">
                <span className="text-[#8a8c92] text-[10px]">
                  Want zero residue immediately?
                </span>
                <button
                  type="button"
                  onClick={handlePurgeAllData}
                  disabled={isPurging}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#e5484d]/10 hover:bg-[#e5484d]/20 text-[#e5484d] border border-[#e5484d]/30 text-[10px] font-medium transition-colors cursor-pointer"
                >
                  <Trash2 className="w-3 h-3" />
                  <span>{isPurging ? 'Purging...' : 'Wipe Session Now'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 border-t border-[#222224] bg-[#171719] flex items-center justify-between">
          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center space-x-1 px-3 py-1.5 rounded-md bg-[#212023] hover:bg-[#2a292e] text-[#8a8c92] hover:text-white text-xs transition-colors cursor-pointer"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Reset Defaults</span>
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="inline-flex items-center space-x-1.5 px-4 py-1.5 rounded-md bg-[#4a8ad6] hover:bg-[#3d77bc] text-white text-xs font-medium transition-colors cursor-pointer"
          >
            <Save className="w-3.5 h-3.5" />
            <span>Save & Apply</span>
          </button>
        </div>
      </div>
    </div>
  );
};
