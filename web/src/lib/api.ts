import axios from 'axios';
import type { AxiosInstance } from 'axios';

const API_BASE_URL = 'http://localhost:8000/api';

interface CreateKBRequest {
  name: string;
}

interface IngestDocumentRequest {
  content: string;
  filename?: string;
  preset_id?: string;
  parser_config?: Record<string, any>;
}

interface QueryRequest {
  query_text: string;
  top_k?: number;
}

interface EvalRequest {
  num_questions?: number;
}

interface CreateRunRequest {
  thread_id: string;
  content: string;
  queue_policy?: string;
}

export interface SSEEvent {
  event: 'message-delta' | 'run-finished';
  content?: string;
  status?: string;
  message_id?: number;
}

export interface GraphNode {
  id: string;
  name: string;
  type: string | null;
}

export interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  type: string | null;
}

export interface EvalRunItem {
  item_index: number;
  query_text: string;
  gold_chunk_ids: string[];
  gold_answer: string;
  generated_answer: string | null;
  retrieved_chunk_ids: string[];
  metrics: Record<string, number | string>;
}

let apiKey: string = '';

export const setApiKey = (newKey: string) => {
  apiKey = newKey;
};

export const getApiKey = (): string => apiKey;

const createClient = (): AxiosInstance => {
  return axios.create({
    baseURL: API_BASE_URL,
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey && { 'X-Api-Key': apiKey }),
    },
  });
};

export const apiClient = {
  // KBs
  listKBs: async () => {
    const client = createClient();
    const res = await client.get('/knowledge/databases');
    return res.data.databases;
  },

  createKB: async (body: CreateKBRequest) => {
    const client = createClient();
    const res = await client.post('/knowledge/databases', body);
    return res.data;
  },

  // Documents
  listDocuments: async (kbId: string) => {
    const client = createClient();
    const res = await client.get(`/knowledge/databases/${kbId}/documents`);
    return res.data.documents;
  },

  ingestDocument: async (kbId: string, body: IngestDocumentRequest) => {
    const client = createClient();
    const res = await client.post(`/knowledge/databases/${kbId}/documents`, body);
    return res.data;
  },

  uploadDocument: async (kbId: string, file: File) => {
    const client = createClient();
    const formData = new FormData();
    formData.append('file', file);
    const res = await client.post(`/knowledge/databases/${kbId}/documents/upload`, formData, {
      headers: { 'Content-Type': undefined },
    });
    return res.data;
  },

  // Query
  queryKB: async (kbId: string, body: QueryRequest) => {
    const client = createClient();
    const res = await client.post(`/knowledge/databases/${kbId}/query`, body);
    return res.data.results;
  },

  // Eval
  runEval: async (kbId: string, body: EvalRequest) => {
    const client = createClient();
    const res = await client.post(`/knowledge/databases/${kbId}/eval`, body);
    return res.data;
  },

  listEvals: async (kbId: string) => {
    const client = createClient();
    const res = await client.get(`/knowledge/databases/${kbId}/eval`);
    return res.data.runs;
  },

  getEvalRun: async (kbId: string, runId: string) => {
    const client = createClient();
    const res = await client.get(`/knowledge/databases/${kbId}/eval/${runId}`);
    return res.data;
  },

  // Graph
  getSubgraph: async (kbId: string, maxNodes = 200): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> => {
    const client = createClient();
    const res = await client.get(`/graph/${kbId}/subgraph`, { params: { max_nodes: maxNodes } });
    return res.data;
  },

  // Agent chat
  createRun: async (body: CreateRunRequest) => {
    const client = createClient();
    const res = await client.post('/agent/runs', body);
    return res.data;
  },

  getThreadHistory: async (threadId: string) => {
    const client = createClient();
    const res = await client.get(`/agent/thread/${threadId}/history`);
    return res.data.history;
  },

  getActiveRun: async (threadId: string) => {
    const client = createClient();
    const res = await client.get(`/agent/thread/${threadId}/active_run`);
    return res.data.run;
  },

  submitFeedback: async (messageId: number, rating: string, reason?: string) => {
    const client = createClient();
    const res = await client.post(`/agent/message/${messageId}/feedback`, { rating, reason });
    return res.data;
  },

  cancelRequest: async (requestId: string) => {
    const client = createClient();
    const res = await client.post(`/agent/requests/${requestId}/cancel`);
    return res.data;
  },

  streamRunEvents: async function* (runId: string, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
    const response = await fetch(`${API_BASE_URL}/agent/runs/${runId}/events`, {
      headers: {
        ...(apiKey && { 'X-Api-Key': apiKey }),
      },
      signal,
    });
    if (!response.body) return;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const messages = buffer.split('\n\n');
      buffer = messages.pop() || '';

      for (const raw of messages) {
        if (!raw.trim() || raw.startsWith(':')) continue;
        let eventType = 'message';
        let data = '';
        for (const line of raw.split('\n')) {
          if (line.startsWith('event: ')) eventType = line.slice(7);
          else if (line.startsWith('data: ')) data = line.slice(6);
        }
        if (!data) continue;
        const parsed = JSON.parse(data);
        yield { event: eventType as SSEEvent['event'], ...parsed };
        if (eventType === 'run-finished') return;
      }
    }
  },
};
