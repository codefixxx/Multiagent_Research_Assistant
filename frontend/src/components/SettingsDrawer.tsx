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

          {/* Optional API Keys */}
          <div className="space-y-3 pt-3 border-t border-[#1b1a1f]">
            <div className="flex items-center space-x-1.5 text-xs font-medium text-[#8a8c92]">
              <Key className="w-3.5 h-3.5 stroke-[1.75]" />
              <span>Custom API Keys (Optional)</span>
            </div>
            <p className="text-xs text-[#8a8c92]/70 leading-relaxed">
              Keys are saved locally in your browser only. Leave empty to use default server configuration.
            </p>

            {/* Gemini */}
            <div className="space-y-1">
              <label className="text-[#8a8c92] text-xs">Google Gemini API Key</label>
              <div className="relative flex items-center">
                <input
                  type={showKey.gemini ? 'text' : 'password'}
                  value={keys.gemini || ''}
                  onChange={(e) => setKeys({ ...keys, gemini: e.target.value })}
                  placeholder="AIzaSy... (uses server default if empty)"
                  className="w-full bg-[#171719] border border-[#222224] rounded-md px-3 py-1.5 pr-8 text-white focus:outline-none text-xs tabular"
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
                  onChange={(e) => setKeys({ ...keys, openai: e.target.value })}
                  placeholder="sk-... (for GPT models)"
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
                  onChange={(e) => setKeys({ ...keys, anthropic: e.target.value })}
                  placeholder="sk-ant-... (for Claude models)"
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
