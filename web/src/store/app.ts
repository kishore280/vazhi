import { create } from 'zustand';
import { setApiKey, apiClient } from '../lib/api';

export interface KB {
  kb_id: string;
  name: string;
  created_at: string;
  created_by: string;
}

export interface Document {
  kb_id: string;
  doc_id: string;
  filename: string;
  created_at: string;
}

export interface QueryResult {
  chunk_id: string;
  content: string;
  score: number;
}

interface AppStore {
  apiKey: string | null;
  kbs: KB[];
  selectedKbId: string | null;
  documents: Document[];
  loading: boolean;
  error: string | null;

  // Auth
  setApiKey: (key: string) => void;
  logout: () => void;

  // KBs
  loadKBs: () => Promise<void>;
  createKB: (name: string) => Promise<void>;
  selectKB: (kbId: string) => void;

  // Documents
  loadDocuments: (kbId: string) => Promise<void>;
  ingestDocument: (kbId: string, content: string, filename?: string) => Promise<void>;
  uploadDocument: (kbId: string, file: File) => Promise<void>;

  // Query
  queryKB: (kbId: string, query: string, topK?: number) => Promise<QueryResult[]>;

  // State reset
  clearError: () => void;
}

export const useAppStore = create<AppStore>((set, get) => ({
  apiKey: null,
  kbs: [],
  selectedKbId: null,
  documents: [],
  loading: false,
  error: null,

  setApiKey: (key: string) => {
    setApiKey(key);
    set({ apiKey: key });
  },

  logout: () => {
    setApiKey('');
    set({ apiKey: null, kbs: [], selectedKbId: null, documents: [] });
  },

  loadKBs: async () => {
    const state = get();
    if (!state.apiKey) return;

    set({ loading: true, error: null });
    try {
      const kbs = await apiClient.listKBs();
      set({ kbs });
    } catch (err) {
      set({ error: (err as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  createKB: async (name: string) => {
    const state = get();
    if (!state.apiKey) return;

    set({ loading: true, error: null });
    try {
      const newKB = await apiClient.createKB({ name });
      set({ kbs: [newKB, ...state.kbs] });
    } catch (err) {
      set({ error: (err as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  selectKB: (kbId: string) => {
    set({ selectedKbId: kbId, documents: [] });
  },

  loadDocuments: async (kbId: string) => {
    set({ loading: true, error: null });
    try {
      const documents = await apiClient.listDocuments(kbId);
      set({ documents });
    } catch (err) {
      set({ error: (err as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  ingestDocument: async (kbId: string, content: string, filename?: string) => {
    set({ loading: true, error: null });
    try {
      await apiClient.ingestDocument(kbId, {
        content,
        filename: filename || 'document.md',
      });
      await get().loadDocuments(kbId);
    } catch (err) {
      set({ error: (err as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  uploadDocument: async (kbId: string, file: File) => {
    set({ loading: true, error: null });
    try {
      await apiClient.uploadDocument(kbId, file);
      await get().loadDocuments(kbId);
    } catch (err) {
      set({ error: (err as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  queryKB: async (kbId: string, query: string, topK = 3) => {
    set({ loading: true, error: null });
    try {
      const results = await apiClient.queryKB(kbId, {
        query_text: query,
        top_k: topK,
      });
      return results;
    } catch (err) {
      set({ error: (err as Error).message });
      return [];
    } finally {
      set({ loading: false });
    }
  },

  clearError: () => {
    set({ error: null });
  },
}));
