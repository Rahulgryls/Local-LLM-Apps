/**
 * LAKO — Zustand Global State Store
 * Manages: available models, selected models, vector DB stats, ingestion status.
 * Session 1: Shell — fully populated in Sessions 3 & 11.
 */

import { create } from 'zustand'

const useAppStore = create((set, get) => ({
  // ── Model state ────────────────────────────────────────────
  availableModels: [],        // All models from GET /api/models
  primaryModel:    'qwen3.5:9b',
  visionModel:     'llava:13b',
  embeddingModel:  'nomic-embed-text',
  modelHealth:     {},        // { primary: bool, vision: bool, embedding: bool }

  setAvailableModels: (models) => set({ availableModels: models }),
  setPrimaryModel:    (model)  => set({ primaryModel: model }),
  setVisionModel:     (model)  => set({ visionModel: model }),
  setEmbeddingModel:  (model)  => set({ embeddingModel: model }),
  setModelHealth:     (health) => set({ modelHealth: health }),

  // ── Vector DB state ────────────────────────────────────────
  vectorStats: {
    status:           'unknown',
    total_chunks:     0,
    collection_count: 0,
    chromadb_path:    '',
  },
  setVectorStats: (stats) => set({ vectorStats: stats }),

  // ── Ingestion state ────────────────────────────────────────
  activeJobId:      null,
  ingestionProgress: 0,       // 0–100
  ingestionStatus:  'idle',   // idle / processing / done / error

  setActiveJobId:       (id)       => set({ activeJobId: id }),
  setIngestionProgress: (progress) => set({ ingestionProgress: progress }),
  setIngestionStatus:   (status)   => set({ ingestionStatus: status }),

  // ── Chat session state (persists across page navigation) ─────
  chatMessages:    [],
  chatRagMode:     'rag',   // 'rag' | 'web'
  chatSelectedDoc: '',
  chatShowDebug:   false,

  setChatMessages:    (msgs)  => set({ chatMessages: msgs }),
  appendChatMessage:  (msg)   => set(s => ({ chatMessages: [...s.chatMessages, msg] })),
  updateLastChatMessage: (updater) =>
    set(s => {
      const msgs = [...s.chatMessages]
      msgs[msgs.length - 1] = updater(msgs[msgs.length - 1])
      return { chatMessages: msgs }
    }),
  clearChatMessages:  ()      => set({ chatMessages: [] }),
  setChatRagMode:     (mode)  => set({ chatRagMode: mode }),
  setChatSelectedDoc: (id)    => set({ chatSelectedDoc: id }),
  setChatShowDebug:   (v)     => set({ chatShowDebug: v }),

  // ── Settings state (mirror of config.json) ─────────────────
  settings: {
    primary_model:        'qwen3.5:9b',
    vision_model:         'llava:13b',
    embedding_model:      'nomic-embed-text',
    ollama_url:           'http://localhost:11434',
    chromadb_path:        '/lako/storage/chromadb',
    confluence_url:       '',
    confluence_email:     '',
    top_k:                5,
    similarity_threshold: 0.7,
    api_key:              '',
  },
  setSettings: (settings) => set({ settings }),
  updateSetting: (key, value) =>
    set(state => ({ settings: { ...state.settings, [key]: value } })),
}))

export default useAppStore
