import type { ApiState, ComposeLoadResponse, FieldUpdateResponse, RenderResponse } from "../types";

async function readError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const payload = (await response.json()) as { detail?: string; message?: string };
    return payload.detail || payload.message || `Request failed with ${response.status}`;
  }
  const text = await response.text();
  return text || `Request failed with ${response.status}`;
}

async function requestJSON<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as T;
}

async function requestText(input: RequestInfo | URL, init?: RequestInit): Promise<string> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.text();
}

export function getState(): Promise<ApiState> {
  return requestJSON<ApiState>("/api/state");
}

export function loadComposeText(text: string): Promise<ComposeLoadResponse> {
  return requestJSON<ComposeLoadResponse>("/api/compose-text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function resetSession(): Promise<{ status: string }> {
  return requestJSON<{ status: string }>("/api/reset", { method: "POST" });
}

export function updateMetaField(target: string, value: string): Promise<FieldUpdateResponse> {
  return requestJSON<FieldUpdateResponse>("/api/meta/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, value }),
  });
}

export function renderCompose(): Promise<RenderResponse> {
  return requestJSON<RenderResponse>("/api/render", { method: "POST" });
}

export function exportCompose(): Promise<string> {
  return requestText("/api/export", { method: "POST" });
}

export function saveLlmConfig(payload: {
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
}): Promise<{ status: string; llm: ApiState["llm"] }> {
  const formData = new FormData();
  formData.set("stage", "stage1");
  formData.set("base_url", payload.base_url);
  if (payload.api_key.trim()) {
    formData.set("api_key", payload.api_key);
  }
  formData.set("model", payload.model);
  formData.set("temperature", String(payload.temperature));
  return requestJSON<{ status: string; llm: ApiState["llm"] }>("/api/llm", {
    method: "POST",
    body: formData,
  });
}
