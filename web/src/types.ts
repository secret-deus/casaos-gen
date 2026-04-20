export interface ServiceItem {
  container: string;
  description: string;
  multilang?: boolean;
  user_input?: boolean;
}

export interface ServiceMeta {
  envs: ServiceItem[];
  ports: ServiceItem[];
  volumes: ServiceItem[];
}

export type ServiceFieldType = "env" | "port" | "volume";

export interface ServiceDescriptionChange {
  target: string;
  value: string;
}

export interface AppMeta {
  title: string;
  tagline: string;
  description: string;
  releaseNotes: string;
  category: string;
  author: string;
  developer: string;
  version: string;
  updateAt: string;
  website: string;
  repo: string;
  support: string;
  docs: string;
  main: string;
  port_map: string;
  scheme: string;
  index: string;
}

export interface EditorMeta {
  app: AppMeta;
  services: Record<string, ServiceMeta>;
}

export interface LlmStageConfig {
  base_url: string | null;
  api_key: boolean;
  model: string;
  temperature: number;
  managed?: string;
}

export interface LlmConfig extends LlmStageConfig {
  stage1: LlmStageConfig;
  stage2: LlmStageConfig;
}

export interface ApiState {
  languages: string[];
  has_compose: boolean;
  has_meta: boolean;
  has_stage2: boolean;
  meta: EditorMeta | null;
  llm: LlmConfig;
  compose_text: string;
}

export interface ComposeLoadResponse {
  status: string;
  message: string;
  meta: EditorMeta;
}

export interface FieldUpdateResponse {
  status: string;
  meta: EditorMeta;
}

export interface RenderResponse {
  status: string;
  compose: Record<string, unknown>;
  warnings: string[];
}
