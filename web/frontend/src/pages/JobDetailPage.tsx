import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { FileStatus } from "../api/client";
import { formatDuration, formatEta, formatStatus, getJob, JobProgress, rerunJob } from "../api/client";

function useJob(jobId: string | undefined) {
  const [job, setJob] = useState<JobProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;

    const fetchJob = () => {
      getJob(jobId)
        .then((data) => {
          if (!cancelled) setJob(data);
        })
        .catch((err) => {
          if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
        });
    };

    fetchJob();
    const timer = setInterval(fetchJob, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId]);

  return { job, error };
}

function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { job, error } = useJob(id);
  const [isRerunning, setRerunning] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const failedFiles = useMemo(() => job?.files.filter((file) => file.status === "failed") ?? [], [job]);

  useEffect(() => {
    if (job?.status !== "running") return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job?.status]);

  const elapsedSeconds = useMemo(() => {
    if (!job?.started_at) return null;
    const startedAt = new Date(job.started_at).getTime();
    if (Number.isNaN(startedAt)) return null;
    const referenceTimestamp = job.finished_at
      ? new Date(job.finished_at).getTime()
      : job.updated_at
        ? new Date(job.updated_at).getTime()
        : null;
    const reference = referenceTimestamp && !Number.isNaN(referenceTimestamp) ? referenceTimestamp : startedAt;
    const baseDiff = (reference - startedAt) / 1000;
    const liveDiff = !job.finished_at && job.status === "running" ? (now - reference) / 1000 : 0;
    const diff = baseDiff + liveDiff;
    return diff > 0 ? diff : 0;
  }, [job?.started_at, job?.updated_at, job?.finished_at, job?.status, now]);

  const elapsedLabel = job?.status === "completed" ? "总耗时" : "已执行时间";

  const fileStatusLabel = (status: FileStatus) => {
    switch (status) {
      case "pending":
        return "待处理";
      case "in_progress":
        return "进行中";
      case "completed":
        return "已完成";
      case "failed":
        return "失败";
      default:
        return status;
    }
  };

  const handleRerun = async () => {
    if (!id) return;
    setRerunning(true);
    try {
      const result = await rerunJob(id);
      navigate(`/jobs/${result.id}`);
    } catch (err) {
      alert(err instanceof Error ? err.message : "重跑失败");
      setRerunning(false);
    }
  };

  if (!id) {
    return <p className="text-danger">缺少任务 ID。</p>;
  }

  if (error) {
    return <p className="text-danger">{error}</p>;
  }

  if (!job) {
    return <p className="text-muted">加载中...</p>;
  }

  return (
    <div className="page page--wide">
      <section className="surface">
        <header className="job-header">
          <div>
            <h2 className="section-title">任务详情 #{job.id}</h2>
            <div className="text-muted">
              {job.repo_url}
              {job.branch ? ` · ${job.branch}` : ""}
            </div>
          </div>
          <div className="job-header__actions">
            <button onClick={() => navigate(`/jobs/${job.id}/preview`)} className="btn-primary">
              预览译文
            </button>
            <button onClick={handleRerun} disabled={isRerunning} className="btn-outline">
              {isRerunning ? "重新排队中..." : "重跑任务"}
            </button>
          </div>
        </header>

        <section className="job-summary">
          <div>
            状态：<span className={`badge ${job.status}`}>{formatStatus(job.status)}</span>
          </div>
          <div>
            文件总数：{job.total_files}，已完成：{job.completed_files}，失败：{job.failed_files}
          </div>
          <div>预计剩余时间：{formatEta(job.eta_seconds)}</div>
          <div>{elapsedLabel}：{formatDuration(elapsedSeconds)}</div>
          {job.error_message && <div className="text-danger">错误信息：{job.error_message}</div>}
          <div className="progress-bar">
            <span style={{ width: `${job.percent_complete}%` }} />
          </div>
        </section>

        <section className="job-files">
          <h3>文件进度</h3>
          <div className="table-wrapper" style={{ maxHeight: 360 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>文件</th>
                  <th>状态</th>
                  <th>更新时间</th>
                  <th>错误</th>
                </tr>
              </thead>
              <tbody>
                {job.files.length === 0 ? (
                  <tr>
                    <td colSpan={4} style={{ textAlign: "center", padding: 24 }}>暂无文件信息</td>
                  </tr>
                ) : (
                  job.files.map((file) => (
                    <tr key={file.path}>
                      <td>{file.path}</td>
                      <td>
                        <span className={`badge ${file.status}`}>{fileStatusLabel(file.status)}</span>
                      </td>
                      <td>{new Date(file.updated_at).toLocaleString()}</td>
                      <td className="text-danger">{file.error}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <h3>日志摘要</h3>
          <pre className="code-viewer code-viewer--panel">{job.log_excerpt || "暂无日志"}</pre>
        </section>

        {failedFiles.length > 0 && (
          <section>
            <h3>失败文件</h3>
            <ul className="list-reset">
              {failedFiles.map((file) => (
                <li key={file.path}>{file.path}: {file.error}</li>
              ))}
            </ul>
          </section>
        )}

        <footer className="job-footer">
          <Link to="/history">返回历史列表</Link>
        </footer>
      </section>
    </div>
  );
}

export default JobDetailPage;
