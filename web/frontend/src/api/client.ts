export type JobStatus = "queued" | "running" | "completed" | "failed";
export type FileStatus = "pending" | "in_progress" | "completed" | "failed";

export interface FileProgress {
  path: string;
  status: FileStatus;
  error?: string | null;
  updated_at: string;
}

export interface JobProgress {
  id: string;
  repo_url: string;
  branch?: string | null;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  total_files: number;
  completed_files: number;
  failed_files: number;
  percent_complete: number;
  eta_seconds?: number | null;
  log_path?: string | null;
  output_path?: string | null;
  output_subdir?: string | null;
  extensions: string[];
  error_message?: string | null;
  log_excerpt?: string | null;
  files: FileProgress[];
}

export interface JobHistoryItem {
  id: string;
  repo_url: string;
  branch?: string | null;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  total_files: number;
  completed_files: number;
  failed_files: number;
  percent_complete: number;
  eta_seconds?: number | null;
  log_excerpt?: string | null;
}

interface HistoryResponse {
  items: JobHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TreeEntry {
  path: string;
  type: "file" | "directory";
}

const API_BASE = "/api";

async function request<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: { "Content-Type": "application/json" },
    ...init
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail?.detail || response.statusText);
  }
  return (await response.json()) as T;
}

export async function createJob(params: {
  repo_url: string;
  extensions: string[];
  output_subdir?: string;
  branch?: string;
}): Promise<JobProgress> {
  const data = await request<{ job: JobProgress }>(`${API_BASE}/jobs`, {
    method: "POST",
    body: JSON.stringify(params)
  });
  return data.job;
}

export async function getJob(id: string): Promise<JobProgress> {
  const data = await request<JobProgress>(`${API_BASE}/jobs/${id}`);
  return data;
}

export async function rerunJob(id: string): Promise<JobProgress> {
  const data = await request<{ job: JobProgress }>(`${API_BASE}/jobs/${id}/rerun`, {
    method: "POST"
  });
  return data.job;
}

export async function deleteJob(id: string): Promise<void> {
  await request(`${API_BASE}/jobs/${id}`, { method: "DELETE" });
}

export async function listJobs(params: {
  limit?: number;
  offset?: number;
  search?: string;
} = {}): Promise<HistoryResponse> {
  const query = new URLSearchParams();
  if (params.limit) query.set("limit", String(params.limit));
  if (params.offset) query.set("offset", String(params.offset));
  if (params.search) query.set("search", params.search);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request<HistoryResponse>(`${API_BASE}/jobs${suffix}`);
}

export async function fetchTree(jobId: string): Promise<TreeEntry[]> {
  const data = await request<{ entries: TreeEntry[] }>(`${API_BASE}/jobs/${jobId}/tree`);
  return data.entries;
}

export async function fetchFileContent(jobId: string, path: string): Promise<{ path: string; content: string }> {
  return request<{ path: string; content: string }>(`${API_BASE}/jobs/${jobId}/preview?path=${encodeURIComponent(path)}`);
}

export function formatEta(seconds?: number | null): string {
  if (seconds === undefined || seconds === null) return "--";
  if (seconds < 60) return `${seconds.toFixed(0)} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.floor(seconds % 60);
  return `${minutes} 分 ${remaining} 秒`;
}

const TZ_SUFFIX_REGEX = /(Z|[+-]\d\d:\d\d)$/;

export function parseTimestamp(value?: string | null): number | null {
  if (!value) return null;
  const normalized = TZ_SUFFIX_REGEX.test(value) ? value : `${value}Z`;
  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    const fallback = Date.parse(value);
    return Number.isNaN(fallback) ? null : fallback;
  }
  return parsed;
}

export function formatTimestamp(value?: string | null): string {
  const timestamp = parseTimestamp(value);
  if (timestamp === null) return "--";
  return new Date(timestamp).toLocaleString();
}

export function formatDuration(seconds?: number | null): string {
  if (seconds === undefined || seconds === null) return "--";
  const totalSeconds = Math.max(0, Math.floor(seconds));
  if (totalSeconds < 60) {
    return `${totalSeconds} 秒`;
  }
  const totalMinutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  if (totalMinutes < 60) {
    return `${totalMinutes} 分 ${remainingSeconds} 秒`;
  }
  const hours = Math.floor(totalMinutes / 60);
  const remainingMinutes = totalMinutes % 60;
  return `${hours} 时 ${remainingMinutes} 分 ${remainingSeconds} 秒`;
}

export function formatStatus(status: JobStatus): string {
  switch (status) {
    case "running":
      return "运行中";
    case "completed":
      return "已完成";
    case "failed":
      return "已失败";
    case "queued":
    default:
      return "排队中";
  }
}
