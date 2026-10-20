import React, { useState, useEffect } from 'react';
import type { ModelMatrix, ApiKeys } from '../types';
import { X, Sliders, Key, Zap, Brain, Eye, EyeOff, Save, RotateCcw } from 'lucide-react';

interface SettingsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (matrix: ModelMatrix, keys: ApiKeys) => void;
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
}) => {
  const [matrix, setMatrix] = useState<ModelMatrix>(DEFAULT_MATRIX);
  const [keys, setKeys] = useState<ApiKeys>({});
  const [showKey, setShowKey] = useState<Record<string, boolean>>({});

  useEffect(() => {
    try {
      const savedMatrix = localStorage.getItem('multiagent_model_matrix');
      if (savedMatrix) setMatrix(JSON.parse(savedMatrix));
      const savedKeys = localStorage.getItem('multiagent_byok_keys');
      if (savedKeys) setKeys(JSON.parse(savedKeys));
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
      localStorage.setItem('multiagent_byok_keys', JSON.stringify(keys));
    } catch {}
    onSave(matrix, keys);
    onClose();
  };

  const handleReset = () => {
    setMatrix(DEFAULT_MATRIX);
    setKeys({});
    try {
      localStorage.removeItem('multiagent_model_matrix');
      localStorage.removeItem('multiagent_byok_keys');
    } catch {}
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-xs flex justify-end">
      <div className="w-full max-w-lg bg-[#101217] border-l border-white/[0.08] shadow-2xl h-full flex flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="px-6 py-5 border-b border-white/[0.08] flex items-center justify-between">
          <div className="flex items-center space-x-2.5">
            <Sliders className="w-5 h-5 text-blue-400" />
            <h3 className="font-semibold text-base text-white">Settings & AI Models</h3>
          </div>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="text-white/40 hover:text-white p-1.5 rounded-lg hover:bg-white/5 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 text-sm">
          {/* Quick Presets */}
          <div className="space-y-2.5">
            <div className="text-xs font-semibold text-white/50 uppercase tracking-wider">
              Quick Presets
            </div>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => handleApplyPreset('fast')}
                className="flex items-center space-x-2 p-3 rounded-xl bg-white/[0.02] hover:bg-white/[0.05] border border-white/[0.08] text-white/90 transition-colors cursor-pointer text-sm font-medium"
              >
                <Zap className="w-4 h-4 text-amber-400" />
                <span>Fast & Efficient</span>
              </button>
              <button
                type="button"
                onClick={() => handleApplyPreset('quality')}
                className="flex items-center space-x-2 p-3 rounded-xl bg-white/[0.02] hover:bg-white/[0.05] border border-white/[0.08] text-white/90 transition-colors cursor-pointer text-sm font-medium"
              >
                <Brain className="w-4 h-4 text-blue-400" />
                <span>Deep Synthesis</span>
              </button>
            </div>
          </div>

          {/* Model Selection */}
          <div className="space-y-3.5">
            <div className="text-xs font-semibold text-white/50 uppercase tracking-wider">
              AI Model Selection
            </div>

            {/* Planner */}
            <div className="space-y-1.5">
              <label className="text-white/70 text-sm">1. Strategy & Planning</label>
              <select
                value={matrix.planner}
                onChange={(e) => setMatrix({ ...matrix, planner: e.target.value })}
                className="w-full bg-[#161820] border border-white/[0.08] rounded-lg px-3.5 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500 cursor-pointer"
              >
                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="claude-3-5-haiku-20241022">Claude 3.5 Haiku</option>
              </select>
            </div>

            {/* Researcher */}
            <div className="space-y-1.5">
              <label className="text-white/70 text-sm">2. Web Research & Gathering</label>
              <select
                value={matrix.researcher}
                onChange={(e) => setMatrix({ ...matrix, researcher: e.target.value })}
                className="w-full bg-[#161820] border border-white/[0.08] rounded-lg px-3.5 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500 cursor-pointer"
              >
                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
                <option value="llama-3.3-70b-versatile">Groq / LLaMA 3.3 70B</option>
              </select>
            </div>

            {/* Reviewer */}
            <div className="space-y-1.5">
              <label className="text-white/70 text-sm">3. Fact & Quality Reviewer</label>
              <select
                value={matrix.reviewer}
                onChange={(e) => setMatrix({ ...matrix, reviewer: e.target.value })}
                className="w-full bg-[#161820] border border-white/[0.08] rounded-lg px-3.5 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500 cursor-pointer"
              >
                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
              </select>
            </div>

            {/* Writer */}
            <div className="space-y-1.5">
              <label className="text-white/70 text-sm">4. Report Writing</label>
              <select
                value={matrix.writer}
                onChange={(e) => setMatrix({ ...matrix, writer: e.target.value })}
                className="w-full bg-[#161820] border border-white/[0.08] rounded-lg px-3.5 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500 cursor-pointer"
              >
                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite</option>
                <option value="gpt-4o">GPT-4o</option>
                <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
              </select>
            </div>
          </div>

          {/* Optional API Keys */}
          <div className="space-y-3.5 pt-3 border-t border-white/[0.06]">
            <div className="flex items-center space-x-2 text-xs font-semibold text-white/50 uppercase tracking-wider">
              <Key className="w-4 h-4 text-blue-400" />
              <span>Custom API Keys (Optional)</span>
            </div>
            <p className="text-xs text-white/50 leading-relaxed">
              Keys are saved locally in your browser only. Leave empty to use default server configuration.
            </p>

            {/* Gemini */}
            <div className="space-y-1.5">
              <label className="text-white/70 text-xs">Google Gemini API Key</label>
              <div className="relative flex items-center">
                <input
                  type={showKey.gemini ? 'text' : 'password'}
                  value={keys.gemini || ''}
                  onChange={(e) => setKeys({ ...keys, gemini: e.target.value })}
                  placeholder="AIzaSy... (uses server default if empty)"
                  className="w-full bg-[#161820] border border-white/[0.08] rounded-lg px-3.5 py-2 pr-9 text-white focus:outline-none font-mono text-sm"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey('gemini')}
                  className="absolute right-2.5 text-white/40 hover:text-white"
                >
                  {showKey.gemini ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* OpenAI */}
            <div className="space-y-1.5">
              <label className="text-white/70 text-xs">OpenAI API Key</label>
              <div className="relative flex items-center">
                <input
                  type={showKey.openai ? 'text' : 'password'}
                  value={keys.openai || ''}
                  onChange={(e) => setKeys({ ...keys, openai: e.target.value })}
                  placeholder="sk-... (for GPT models)"
                  className="w-full bg-[#161820] border border-white/[0.08] rounded-lg px-3.5 py-2 pr-9 text-white focus:outline-none font-mono text-sm"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey('openai')}
                  className="absolute right-2.5 text-white/40 hover:text-white"
                >
                  {showKey.openai ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Anthropic */}
            <div className="space-y-1.5">
              <label className="text-white/70 text-xs">Anthropic API Key</label>
              <div className="relative flex items-center">
                <input
                  type={showKey.anthropic ? 'text' : 'password'}
                  value={keys.anthropic || ''}
                  onChange={(e) => setKeys({ ...keys, anthropic: e.target.value })}
                  placeholder="sk-ant-... (for Claude models)"
                  className="w-full bg-[#161820] border border-white/[0.08] rounded-lg px-3.5 py-2 pr-9 text-white focus:outline-none font-mono text-sm"
                />
                <button
                  type="button"
                  onClick={() => toggleShowKey('anthropic')}
                  className="absolute right-2.5 text-white/40 hover:text-white"
                >
                  {showKey.anthropic ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-white/[0.08] bg-white/[0.01] flex items-center justify-between">
          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center space-x-1.5 px-3.5 py-2 rounded-lg bg-white/[0.03] hover:bg-white/[0.07] text-white/70 hover:text-white text-sm transition-colors cursor-pointer"
          >
            <RotateCcw className="w-4 h-4" />
            <span>Reset Defaults</span>
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="inline-flex items-center space-x-2 px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors cursor-pointer"
          >
            <Save className="w-4 h-4" />
            <span>Save & Apply</span>
          </button>
        </div>
      </div>
    </div>
  );
};
