import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import hljs from "highlight.js/lib/common";
import "highlight.js/styles/github-dark.css";
import "github-markdown-css/github-markdown.css";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { fetchFileContent, fetchTree, TreeEntry } from "../api/client";

type TreeNode = {
  name: string;
  path: string;
  type: "file" | "directory";
  children: TreeNode[];
};

type PreviewTab = "preview" | "code" | "raw";

function buildTree(entries: TreeEntry[]): TreeNode {
  const root: TreeNode = { name: ".", path: ".", type: "directory", children: [] };
  const dirMap: Record<string, TreeNode> = { [root.path]: root };

  entries.forEach((entry) => {
    if (entry.path === ".") return;
    const parts = entry.path.split("/").filter(Boolean);
    let current = root;
    let currentPath = "";
    parts.forEach((part, index) => {
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      const isLast = index === parts.length - 1;
      const nodeKey = currentPath;
      const existing = dirMap[nodeKey];
      if (!existing) {
        const node: TreeNode = {
          name: part,
          path: nodeKey,
          type: isLast ? entry.type : "directory",
          children: [],
        };
        if (!current.children.some((child) => child.name === part)) {
          current.children.push(node);
        }
        if (node.type === "directory") {
          dirMap[nodeKey] = node;
          current = node;
        }
      } else {
        current = existing;
      }
    });
  });

  const sortChildren = (node: TreeNode) => {
    node.children.sort((a, b) => {
      if (a.type === b.type) return a.name.localeCompare(b.name);
      return a.type === "directory" ? -1 : 1;
    });
    node.children.forEach(sortChildren);
  };
  sortChildren(root);
  return root;
}

function TreeView({ node, onSelect, active }: { node: TreeNode; onSelect: (path: string) => void; active: string | null }) {
  return (
    <ul className="preview-tree">
      {node.children.map((child) => (
        <li key={child.path} className="preview-tree__node">
          {child.type === "directory" ? (
            <details open>
              <summary className="preview-tree__folder">{child.name}</summary>
              <TreeView node={child} onSelect={onSelect} active={active} />
            </details>
          ) : (
            <button
              type="button"
              onClick={() => onSelect(child.path)}
              className={`preview-tree__item${active === child.path ? " is-active" : ""}`}
            >
              {child.name}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

function PreviewPage() {
  const { id } = useParams<{ id: string }>();
  const [entries, setEntries] = useState<TreeEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<PreviewTab>("preview");

  useEffect(() => {
    if (!id) return;
    fetchTree(id)
      .then((data) => setEntries(data))
      .catch((err) => setError(err instanceof Error ? err.message : "加载目录失败"));
  }, [id]);

  useEffect(() => {
    if (!id || !selected) return;
    fetchFileContent(id, selected)
      .then((data) => setContent(data.content))
      .catch((err) => setError(err instanceof Error ? err.message : "加载文件失败"));
  }, [id, selected]);

  useEffect(() => {
    if (selected || entries.length === 0) return;
    const firstFile = entries.find((entry) => entry.type === "file");
    if (firstFile) {
      setSelected(firstFile.path);
    }
  }, [entries, selected]);

  useEffect(() => {
    setTab("preview");
  }, [selected]);

  const tree = useMemo(() => buildTree(entries), [entries]);
  const isMarkdown = useMemo(() => (selected ? /\.(md|markdown|mdown|mkd)$/i.test(selected) : false), [selected]);
  const highlighted = useMemo(() => {
    if (!content) return "";
    return hljs.highlightAuto(content).value;
  }, [content]);

  const markdownRemarkPlugins = useMemo(() => [remarkGfm], []);
  const markdownRehypePlugins = useMemo(() => [rehypeHighlight as unknown as any], []);

  const renderPreview = () => {
    if (!selected) {
      return <p className="preview-panel__placeholder">请选择一个文件以预览内容。</p>;
    }

    if (tab === "raw") {
      return (
        <pre className="code-viewer code-viewer--panel">{content}</pre>
      );
    }

    if (tab === "code") {
      return (
        <pre className="code-viewer code-viewer--panel">
          <code dangerouslySetInnerHTML={{ __html: highlighted }} />
        </pre>
      );
    }

    if (isMarkdown) {
      return (
        <article className="markdown-body">
          <ReactMarkdown remarkPlugins={markdownRemarkPlugins} rehypePlugins={markdownRehypePlugins}>
            {content}
          </ReactMarkdown>
        </article>
      );
    }

    return (
      <pre className="code-viewer code-viewer--panel">
        <code dangerouslySetInnerHTML={{ __html: highlighted }} />
      </pre>
    );
  };

  if (!id) {
    return <p className="text-danger">缺少任务 ID。</p>;
  }

  return (
    <div className="page page--wide">
      <div className="preview-root">
        <aside className="preview-nav">
          <div className="preview-nav__header">
            <span className="preview-nav__title">FILES</span>
            <Link to={`/jobs/${id}`} className="preview-nav__link">返回任务</Link>
          </div>
          {error && <p className="preview-nav__error">{error}</p>}
          {entries.length === 0 ? (
            <p className="preview-nav__placeholder">暂无译文，请等待任务完成。</p>
          ) : (
            <TreeView node={tree} onSelect={setSelected} active={selected} />
          )}
        </aside>
        <main className="preview-main">
          <header className="preview-main__toolbar">
            <span className="preview-main__filename">{selected || "选择一个文件"}</span>
            <div className="preview-tabs">
              {(["preview", "code", "raw"] as PreviewTab[]).map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`preview-tab${tab === item ? " is-active" : ""}`}
                  onClick={() => setTab(item)}
                >
                  {item === "preview" ? "Preview" : item === "code" ? "Code" : "Raw"}
                </button>
              ))}
            </div>
          </header>
          <section className="preview-panel">{renderPreview()}</section>
        </main>
      </div>
    </div>
  );
}

export default PreviewPage;
