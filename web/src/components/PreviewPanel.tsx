import { useMemo, useState } from "react";
import type { EditorMeta } from "../types";
import type { PreviewTab } from "../store/workspace";

interface PreviewPanelProps {
  tab: PreviewTab;
  onTabChange: (tab: PreviewTab) => void;
  composeText: string;
  renderedYaml: string;
  meta: EditorMeta | null;
  warnings: string[];
}

export function PreviewPanel({ tab, onTabChange, composeText, renderedYaml, meta, warnings }: PreviewPanelProps) {
  const tabs: PreviewTab[] = ["rendered", "meta", "compose"];
  const [copied, setCopied] = useState(false);
  const content =
    tab === "compose"
      ? composeText || "No compose loaded."
      : tab === "meta"
        ? JSON.stringify(meta, null, 2)
        : renderedYaml || "Render the current workspace to preview final YAML.";

  const activeLabel = tab === "rendered" ? "Rendered YAML" : tab === "meta" ? "Meta JSON" : "Source Compose";
  const contentStats = useMemo(() => {
    const lines = content ? content.split("\n").length : 0;
    const chars = content.length;
    return `${lines} lines · ${chars} chars`;
  }, [content]);

  return (
    <section className="previewShell">
      <div className="previewShell__toolbar">
        <div>
          <div className="previewShell__label">{activeLabel}</div>
          <div className="previewShell__meta">{contentStats}</div>
        </div>
        <button
          className="secondaryButton"
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(content);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      <div className="previewShell__tabs">
        {tabs.map((item) => (
          <button
            key={item}
            className={`tabButton ${item === tab ? "tabButton--active" : ""}`}
            type="button"
            onClick={() => onTabChange(item)}
          >
            {item === "rendered" ? "Rendered YAML" : item === "meta" ? "Meta JSON" : "Source Compose"}
          </button>
        ))}
      </div>

      {warnings.length ? (
        <div className="warningList">
          {warnings.map((warning) => (
            <div key={warning} className="warningList__item">
              {warning}
            </div>
          ))}
        </div>
      ) : null}

      <pre className="codeBlock">{content}</pre>
    </section>
  );
}
