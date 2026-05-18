const API = "/api";

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

export interface MarketEnv {
  trade_date: string;
  env_score: number;
  limit_up_count: number;
  up_down_ratio: number;
  index_pct: number;
  conclusion: string;
  can_long: boolean;
}

export interface SectorScore {
  sector_code: string;
  sector_name: string;
  total_score: number;
  stage: string;
  rank: number;
  persistence_score: number;
  capital_score: number;
  breadth_score: number;
  leader_score: number;
  relative_score: number;
  position_hint: string;
  leader_stock?: string;
  leader_stock_name?: string;
  leader_streak?: number;
  pct_change?: number;
  is_filtered?: boolean;
  filter_reason?: string | null;
  is_scored?: boolean;
}

export interface SectorList {
  trade_date: string | null;
  universe_total: number;
  sectors_scored: number;
  demo_mode: boolean;
  is_live_data?: boolean;
  data_source?: string;
  data_source_label?: string;
  data_source_short?: string;
  jq_configured?: boolean;
  sectors: SectorScore[];
}

export interface TaskStatus {
  task_type: string;
  status: "idle" | "running" | "done" | "failed";
  message: string;
  trade_date?: string | null;
  scan_start_date?: string | null;
  scan_end_date?: string | null;
  trade_days?: string[];
  progress: number;
  total: number;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
}

export interface JqDataRange {
  start: string;
  end: string;
  latest_trade_day: string;
  label: string;
}

export interface DataSourceOption {
  id: string;
  label: string;
  description: string;
  configured: boolean;
  active: boolean;
}

export interface DataSourcesResponse {
  current: string;
  active_adapter: string;
  options: DataSourceOption[];
}

export interface ConceptItem {
  sector_code: string;
  sector_name: string;
}

export interface ScanSectorsResponse {
  use_explicit_selection: boolean;
  selected_codes: string[];
  universe: ConceptItem[];
}

export interface SystemStatus {
  adapter: string;
  demo_mode: boolean;
  is_live_data: boolean;
  data_source_label: string;
  data_source_short: string;
  data_source?: string;
  jq_configured: boolean;
  tushare_configured?: boolean;
  universe_total: number;
  ingest_max_concepts: number;
  ingest_concept_filter?: string;
  scan_scope_label?: string;
  ingest_max_stocks_per_concept?: number;
  use_explicit_sector_selection?: boolean;
  selected_sector_count?: number;
  scan_volatile_storage?: boolean;
  scan_task: TaskStatus;
  jq_data_range?: JqDataRange | null;
  default_scan_date?: string | null;
  default_scan_start?: string | null;
  default_scan_end?: string | null;
}

export interface Dashboard {
  trade_date: string | null;
  market_env: MarketEnv | null;
  top_sectors: SectorScore[];
}

export interface Alert {
  id: number;
  trade_date: string;
  sector_code: string;
  sector_name: string;
  alert_code: string;
  human_reason: string;
  created_at: string;
}

export interface ScoreDimension {
  key: string;
  label: string;
  weight_pct: number;
  score: number;
  description: string;
}

export interface StockPctDay {
  trade_date: string;
  pct_change: number;
}

export interface SectorDetail {
  sector_code: string;
  sector_name: string;
  trade_date: string;
  pct_display_days?: string[];
  stage: string;
  total_score: number;
  scores: Record<string, number>;
  score_dimensions?: ScoreDimension[];
  limit_up_count: number;
  big_yang_count: number;
  net_inflow_main: number;
  net_inflow_yi: number;
  inflow_days: number;
  up_count: number;
  total_count: number;
  up_ratio: number;
  blow_up_rate: number;
  position_hint: string;
  leader?: { stock_code: string; stock_name?: string; streak: number; pct_change: number };
  stocks: Array<{
    stock_code: string;
    stock_name?: string;
    pct_change: number;
    pct_trade_date?: string;
    is_limit_up: boolean;
    limit_up_streak: number;
    money: number;
    pct_history?: StockPctDay[];
  }>;
  history: Array<{ trade_date: string; total_score: number; stage: string }>;
  flow_history?: Array<{
    trade_date: string;
    net_inflow_wan: number;
    net_inflow_yi: number;
  }>;
}

export interface BacktestRun {
  id: number;
  status: string;
  strategy_id: string;
  start_date: string;
  end_date: string;
  progress: number;
  total_days: number;
  error_message?: string;
  created_at: string;
  finished_at?: string;
}

export interface BacktestReport {
  run: BacktestRun;
  metrics?: Record<string, number>;
  equity_curve: Array<{ trade_date: string; equity: number; benchmark: number }>;
  stage_win_rates: Record<string, number>;
  trade_mode_note?: string;
  strategy_name_cn?: string;
}

export interface BacktestTrade {
  id: number;
  sector_code: string;
  sector_name: string;
  stock_code: string;
  stock_name?: string;
  sell_stock_code?: string;
  sell_stock_name?: string;
  alert_code: string;
  alert_name_cn?: string;
  signal_date?: string;
  entry_date: string;
  exit_date?: string;
  entry_price: number;
  exit_price?: number;
  return_pct?: number;
  holding_days?: number;
  trade_mode?: string;
  entry_timing_cn?: string;
  exit_timing_cn?: string;
  human_reason: string;
}

export const api = {
  health: () => fetchJson<{ status: string; adapter?: string; universe_total?: number }>("/health"),
  systemStatus: () => fetchJson<SystemStatus>("/system/status"),
  dataSources: () => fetchJson<DataSourcesResponse>("/system/data-sources"),
  setDataSource: (source: string) =>
    fetchJson<{ message: string; adapter: string }>("/system/data-source", {
      method: "POST",
      body: JSON.stringify({ source }),
    }),
  getScanSectors: () => fetchJson<ScanSectorsResponse>("/system/scan-sectors"),
  setScanSectors: (body: {
    use_explicit_selection: boolean;
    selected_codes: string[];
  }) =>
    fetchJson<{ message: string; selected_count: number }>("/system/scan-sectors", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listConcepts: () => fetchJson<ConceptItem[]>("/concepts"),
  setIngestSettings: (maxStocksPerConcept: number) =>
    fetchJson<{ message: string; ingest_max_stocks_per_concept: number }>(
      "/system/ingest-settings",
      {
        method: "POST",
        body: JSON.stringify({ max_stocks_per_concept: maxStocksPerConcept }),
      }
    ),
  scanTaskStatus: () => fetchJson<TaskStatus>("/tasks/scan"),
  dashboard: (tradeDate?: string) => {
    const q = tradeDate ? `?trade_date=${tradeDate}` : "";
    return fetchJson<Dashboard>(`/dashboard${q}`);
  },
  clearData: () =>
    fetchJson<{ message: string; deleted?: Record<string, number> }>(
      "/system/clear-data",
      { method: "POST" }
    ),
  listSectors: (tradeDate?: string, scoredOnly = true, includeAll = false) => {
    const params = new URLSearchParams();
    if (tradeDate) params.set("trade_date", tradeDate);
    if (includeAll) params.set("scored_only", "false");
    else if (scoredOnly) params.set("scored_only", "true");
    const q = params.toString();
    return fetchJson<SectorList>(`/sectors${q ? `?${q}` : ""}`);
  },
  scanLatest: (opts?: { startDate?: string; endDate?: string; tradeDate?: string }) => {
    const params = new URLSearchParams();
    if (opts?.startDate) params.set("start_date", opts.startDate);
    if (opts?.endDate) params.set("end_date", opts.endDate);
    if (opts?.tradeDate) params.set("trade_date", opts.tradeDate);
    const q = params.toString();
    return fetchJson<{
      trade_date: string;
      start_date?: string;
      end_date?: string;
      trade_days?: string[];
      status?: string;
      message?: string;
      jq_data_range?: string;
    }>(`/scan/latest${q ? `?${q}` : ""}`, { method: "POST" });
  },
  alerts: (tradeDate?: string) =>
    fetchJson<Alert[]>(`/alerts${tradeDate ? `?trade_date=${tradeDate}` : ""}`),
  sector: (code: string, tradeDate?: string) =>
    fetchJson<SectorDetail>(
      `/sectors/${code}${tradeDate ? `?trade_date=${tradeDate}` : ""}`
    ),
  review: (date: string) => fetchJson<{ trade_date: string; sectors: unknown[] }>(`/review/${date}`),
  createBacktest: (body: {
    strategy_id: string;
    start_date: string;
    end_date: string;
    params?: Record<string, unknown>;
  }) =>
    fetchJson<BacktestRun>("/backtest/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listBacktests: () => fetchJson<BacktestRun[]>("/backtest/runs"),
  getBacktest: (id: number) => fetchJson<BacktestRun>(`/backtest/runs/${id}`),
  backtestReport: (id: number) => fetchJson<BacktestReport>(`/backtest/runs/${id}/report`),
  backtestTrades: (id: number) => fetchJson<BacktestTrade[]>(`/backtest/runs/${id}/trades`),
};
