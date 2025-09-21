import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { createJob, JobHistoryItem, listJobs } from "../api/client";

interface CreatedJobState {
  id: string;
  repoUrl: string;
}

function SubmitJobPage() {
  const [repoUrl, setRepoUrl] = useState("https://github.com/");
  const [extensions, setExtensions] = useState("md,txt");
  const [outputDir, setOutputDir] = useState("");
  const [branch, setBranch] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdJob, setCreatedJob] = useState<CreatedJobState | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobHistoryItem[]>([]);

  useEffect(() => {
    listJobs({ limit: 5 }).then((data) => setRecentJobs(data.items)).catch(() => undefined);
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const job = await createJob({
        repo_url: repoUrl.trim(),
        extensions: extensions.split(",").map((item) => item.trim()).filter(Boolean),
        output_subdir: outputDir.trim() || undefined,
        branch: branch.trim() || undefined,
      });
      setCreatedJob({ id: job.id, repoUrl: job.repo_url });
      const historyItem: JobHistoryItem = {
        id: job.id,
        repo_url: job.repo_url,
        branch: job.branch,
        status: job.status,
        created_at: job.created_at,
        updated_at: job.updated_at,
        total_files: job.total_files,
        completed_files: job.completed_files,
        failed_files: job.failed_files,
        percent_complete: job.percent_complete,
        eta_seconds: job.eta_seconds,
        log_excerpt: job.log_excerpt,
      };
      setRecentJobs((jobs) => [historyItem, ...jobs].slice(0, 5));
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="page">
      <section className="surface">
        <h2 className="section-title">提交新的翻译任务</h2>
      <form onSubmit={handleSubmit} className="form-grid">
          <label className="field">
            <span>GitHub 仓库地址</span>
            <input
              type="url"
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              placeholder="https://github.com/owner/repo"
              required
            />
          </label>
          <label className="field">
            <span>需要翻译的文件扩展名（使用逗号分隔）</span>
            <input
              type="text"
              value={extensions}
              onChange={(event) => setExtensions(event.target.value)}
              placeholder="md,txt"
            />
          </label>
          <label className="field">
            <span>输出目录（可选，用于归档译文）</span>
            <input
              type="text"
              value={outputDir}
              onChange={(event) => setOutputDir(event.target.value)}
              placeholder="例如: project-a"
            />
          </label>
          <label className="field">
            <span>分支名称（默认使用仓库默认分支）</span>
            <input
              type="text"
              value={branch}
              onChange={(event) => setBranch(event.target.value)}
              placeholder="例如: main"
            />
          </label>
          <button type="submit" className="btn-primary" disabled={isSubmitting}>
            {isSubmitting ? "正在提交..." : "开始翻译"}
          </button>
        </form>
        {error && <p className="text-danger">{error}</p>}
        {createdJob && (
          <div className="notice">
            已创建任务 <strong>{createdJob.id}</strong>{" "}
            <Link to={`/jobs/${createdJob.id}`} className="notice__link">
              查看进度
            </Link>
          </div>
        )}
      </section>

      <section className="surface">
        <h3 className="section-title">最近任务</h3>
        {recentJobs.length === 0 ? (
          <p className="text-muted">暂无历史记录。</p>
        ) : (
          <ul className="list-reset recent-list">
            {recentJobs.map((job) => (
              <li key={job.id} className="recent-list__item">
                <div className="recent-list__content">
                  <div>
                    <div className="recent-list__repo">{job.repo_url}</div>
                    <div className="recent-list__id">#{job.id}{job.branch ? ` · ${job.branch}` : ""}</div>
                  </div>
                  <Link to={`/jobs/${job.id}`}>查看详情</Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export default SubmitJobPage;
