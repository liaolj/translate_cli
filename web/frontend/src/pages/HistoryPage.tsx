import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { deleteJob, formatEta, formatStatus, JobHistoryItem, listJobs, rerunJob } from "../api/client";

const PAGE_SIZE = 10;

function HistoryPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<JobHistoryItem[]>([]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [isLoading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    listJobs({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, search: query || undefined })
      .then((data) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [page, query]);

  const totalPages = useMemo(() => Math.ceil(total / PAGE_SIZE), [total]);

  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPage(0);
    setQuery(search.trim());
  };

  const handleRerun = async (id: string) => {
    try {
      const job = await rerunJob(id);
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重跑失败");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除该任务及其产出吗？")) return;
    await deleteJob(id).catch((err) => setError(err instanceof Error ? err.message : "删除失败"));
    setItems((prev) => prev.filter((item) => item.id !== id));
    setTotal((prev) => Math.max(prev - 1, 0));
  };

  return (
    <div className="page">
      <section className="surface">
        <h2 className="section-title">任务历史</h2>
        <form onSubmit={handleSearch} className="history-search">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="按仓库 URL 搜索"
          />
          <button type="submit" className="btn-primary">
            搜索
          </button>
        </form>
        {error && <p className="text-danger">{error}</p>}
        {isLoading ? (
          <p className="text-muted">加载中...</p>
        ) : (
          <div className="table-wrapper">
            <table className="table">
              <thead>
                <tr>
                  <th>任务 ID</th>
                  <th>仓库</th>
                  <th>分支</th>
                  <th>状态</th>
                  <th>完成度</th>
                  <th>预计剩余</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ textAlign: "center", padding: 24 }}>暂无数据</td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link to={`/jobs/${item.id}`}>{item.id}</Link>
                      </td>
                      <td>{item.repo_url}</td>
                      <td>{item.branch || "默认分支"}</td>
                      <td><span className={`badge ${item.status}`}>{formatStatus(item.status)}</span></td>
                      <td>{item.percent_complete.toFixed(1)}%</td>
                      <td>{formatEta(item.eta_seconds)}</td>
                      <td className="history-actions">
                        <button onClick={() => navigate(`/jobs/${item.id}`)} className="btn-primary">
                          详情
                        </button>
                        <button onClick={() => handleRerun(item.id)} className="btn-outline">
                          重跑
                        </button>
                        <button onClick={() => handleDelete(item.id)} className="btn-danger">
                          删除
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
        <div className="history-pagination">
          <div>共 {total} 条记录</div>
          <div className="history-pagination__controls">
            <button onClick={() => setPage((p) => Math.max(p - 1, 0))} disabled={page === 0} className="btn-outline">
              上一页
            </button>
            <span>
              {totalPages === 0 ? 0 : page + 1} / {Math.max(totalPages, 1)}
            </span>
            <button
              onClick={() => setPage((p) => (p + 1 < totalPages ? p + 1 : p))}
              disabled={page + 1 >= totalPages}
              className="btn-outline"
            >
              下一页
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

export default HistoryPage;
