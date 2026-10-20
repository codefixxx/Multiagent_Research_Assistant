export type JobStatus = 
  | 'idle'
  | 'pending'
  | 'planning'
  | 'researching'
  | 'consolidating'
  | 'writing'
  | 'completed'
  | 'failed'
  | 'budget_exceeded';

export interface ModelMatrix {
  planner: string;
  researcher: string;
  reviewer: string;
  writer: string;
}

export interface ApiKeys {
  gemini?: string;
  openai?: string;
  anthropic?: string;
  groq?: string;
  tavily?: string;
}

export interface Citation {
  citation_id: string;
  source_url: string;
  verified_claim: string;
  publish_date?: string;
  is_verified?: boolean;
}

export interface SubQuestionItem {
  id: string;
  text: string;
  status: 'waiting' | 'active' | 'completed' | 'revision';
  findingsCount: number;
  isRevision?: boolean;
}

export interface StageCostAttribution {
  stage: string;
  agent_role: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  stage_cost_usd: number;
}

export interface RunCostSummary {
  total_cost_usd: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  stage_attributions: StageCostAttribution[];
}

export interface RAGScore {
  composite_grade?: string;
  grade?: string;
  composite_score?: number;
  overall_score?: number;
  groundedness_score: number;
  citation_precision_score?: number;
  citation_precision?: number;
  subquestion_coverage_score?: number;
  coverage_score?: number;
  verified_claims_ratio?: number;
  findings_count?: number;
  total_citations?: number;
  verified_citations_count?: number;
  summary?: string;
}

export interface TraceSpan {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  run_id?: string;
  start_time: string;
  end_time: string;
  start_time_epoch_ms: number;
  duration_ms: number;
  status: string;
  error?: string | null;
  attributes: Record<string, any>;
}

export interface ResearchReport {
  title: string;
  markdown_output: string;
  summary?: string;
  key_findings?: string[];
  citations?: Citation[];
  created_at?: string;
}

export interface ResearchJobData {
  run_id: string;
  status: JobStatus;
  query: string;
  report?: ResearchReport | null;
  cost_summary?: RunCostSummary | null;
  rag_score?: RAGScore | null;
  findings_count?: number;
  citations_count?: number;
  error_message?: string | null;
  sub_questions?: string[];
  created_at?: string;
}

export interface StreamLogEntry {
  id: string;
  timestamp: string;
  source: string;
  message: string;
  type?: 'system' | 'planner' | 'researcher' | 'reviewer' | 'consolidator' | 'writer' | 'error';
}
