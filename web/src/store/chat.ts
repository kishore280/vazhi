import { create } from 'zustand';
import { apiClient } from '../lib/api';

export interface ChatMessage {
  id: number | string;
  role: string;
  type: string;
  content: string;
  created_at: string;
  run_id: string | null;
  streaming?: boolean;
}

interface ChatStore {
  threadId: string | null;
  messages: ChatMessage[];
  sending: boolean;
  error: string | null;
  activeRequestId: string | null;
  abortController: AbortController | null;

  startThread: (threadId: string) => void;
  loadHistory: (threadId: string) => Promise<void>;
  sendMessage: (threadId: string, content: string) => Promise<void>;
  stopGeneration: () => Promise<void>;
  clearError: () => void;
}

export const useChatStore = create<ChatStore>((set, get) => ({
  threadId: null,
  messages: [],
  sending: false,
  error: null,
  activeRequestId: null,
  abortController: null,

  startThread: (threadId: string) => {
    set({ threadId, messages: [] });
  },

  loadHistory: async (threadId: string) => {
    set({ error: null });
    try {
      const history = await apiClient.getThreadHistory(threadId);
      set({
        threadId,
        messages: history.map((m: any) => ({
          id: m.id,
          role: m.role,
          type: m.type,
          content: m.content,
          created_at: m.created_at,
          run_id: m.run_id,
        })),
      });
    } catch (err) {
      set({ error: (err as Error).message });
    }
  },

  sendMessage: async (threadId: string, content: string) => {
    const userMessage: ChatMessage = {
      id: `local-${Date.now()}`,
      role: 'user',
      type: 'human',
      content,
      created_at: new Date().toISOString(),
      run_id: null,
    };

    const assistantMessage: ChatMessage = {
      id: `streaming-${Date.now()}`,
      role: 'assistant',
      type: 'ai',
      content: '',
      created_at: new Date().toISOString(),
      run_id: null,
      streaming: true,
    };

    const abortController = new AbortController();

    set((state) => ({
      messages: [...state.messages, userMessage, assistantMessage],
      sending: true,
      error: null,
      abortController,
    }));

    try {
      const run = await apiClient.createRun({ thread_id: threadId, content });
      set({ activeRequestId: run.request_id });

      for await (const evt of apiClient.streamRunEvents(run.run_id, abortController.signal)) {
        if (evt.event === 'message-delta' && evt.content) {
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantMessage.id ? { ...m, content: m.content + evt.content } : m
            ),
          }));
        } else if (evt.event === 'run-finished') {
          set((state) => ({
            messages: state.messages.map((m) =>
              m.id === assistantMessage.id ? { ...m, streaming: false } : m
            ),
          }));
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        set({ error: (err as Error).message });
      }
      set((state) => ({
        messages: state.messages.map((m) =>
          m.id === assistantMessage.id ? { ...m, streaming: false } : m
        ),
      }));
    } finally {
      set({ sending: false, activeRequestId: null, abortController: null });
    }
  },

  stopGeneration: async () => {
    const { activeRequestId, abortController } = get();
    abortController?.abort();
    if (activeRequestId) {
      try {
        await apiClient.cancelRequest(activeRequestId);
      } catch {
        // request may have already finished server-side; nothing to do
      }
    }
  },

  clearError: () => {
    set({ error: null });
  },
}));
