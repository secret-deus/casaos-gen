(() => {
  const root = (window.CasaOSEditor = window.CasaOSEditor || {});
  root.utils = root.utils || {};
  root.api = root.api || {};

  const cx =
    root.utils.cx ||
    ((...parts) =>
      parts
        .flatMap((part) => {
          if (!part) {
            return [];
          }
          if (Array.isArray(part)) {
            return part;
          }
          if (typeof part === "object") {
            return Object.entries(part)
              .filter(([, value]) => Boolean(value))
              .map(([key]) => key);
          }
          return [String(part)];
        })
        .map((item) => String(item).trim())
        .filter(Boolean)
        .join(" "));

  const clamp =
    root.utils.clamp ||
    ((value, min, max) => {
      const numberValue = Number(value);
      if (Number.isNaN(numberValue)) {
        return min;
      }
      return Math.min(max, Math.max(min, numberValue));
    });

  const uid =
    root.utils.uid ||
    (() => {
      let counter = 0;
      return (prefix = "id") => {
        counter += 1;
        return `${prefix}-${Date.now()}-${counter}`;
      };
    })();

  const formatBytes =
    root.utils.formatBytes ||
    ((bytes) => {
      const value = Number(bytes);
      if (!Number.isFinite(value) || value <= 0) {
        return "0 B";
      }
      const units = ["B", "KB", "MB", "GB"];
      const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
      const size = value / Math.pow(1024, exponent);
      const precision = size >= 10 || exponent === 0 ? 0 : 1;
      return `${size.toFixed(precision)} ${units[exponent]}`;
    });

  async function requestJSON(url, options) {
    const response = await fetch(url, options);
    const hasJSON = response.headers.get("content-type")?.includes("application/json");
    const data = hasJSON ? await response.json() : {};
    if (!response.ok) {
      const detail = data.detail || data.message || "Request failed";
      throw new Error(detail);
    }
    return data;
  }

  async function requestText(url, options) {
    const response = await fetch(url, options);
    const text = await response.text();
    if (!response.ok) {
      let detail = "Request failed";
      try {
        const payload = JSON.parse(text);
        detail = payload.detail || detail;
      } catch {
        detail = text || detail;
      }
      throw new Error(detail);
    }
    return text;
  }

  function safeJSONStringify(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value ?? "");
    }
  }

  function readFileAsText(file) {
    return new Promise((resolve, reject) => {
      if (!file) {
        resolve("");
        return;
      }
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error || new Error("Failed to read file"));
      reader.readAsText(file);
    });
  }

  async function copyToClipboard(text) {
    const value = String(text ?? "");
    if (!value) {
      return false;
    }
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.left = "-10000px";
    textarea.style.top = "-10000px";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    try {
      const ok = document.execCommand("copy");
      return ok;
    } finally {
      textarea.remove();
    }
  }

  root.utils.cx = cx;
  root.utils.clamp = clamp;
  root.utils.uid = uid;
  root.utils.formatBytes = formatBytes;
  root.utils.safeJSONStringify = safeJSONStringify;
  root.utils.readFileAsText = readFileAsText;
  root.utils.copyToClipboard = copyToClipboard;

  root.api.requestJSON = root.api.requestJSON || requestJSON;
  root.api.requestText = root.api.requestText || requestText;
})();

