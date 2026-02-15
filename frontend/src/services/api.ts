export interface ScreenshotRef {
  memory_id: string;
  image_base64: string;
  timestamp?: string;
  source_url?: string;
  category?: string;
}

export interface ChatResponse {
  answer: string;
  confidence: number;
  sources: string[];
  screenshots: ScreenshotRef[];
  processing_time_ms: number;
  intent_detected: string;
  uncertain: boolean;
}

export interface FolderStatus {
  file_count: number;
  watcher_running: boolean;
  total_size_mb?: number;
  last_scan?: string;
}

export interface MemoryStats {
  total_memories: number;
  memories_today: number;
  memories_week: number;
  categories: { name: string; count: number }[];
  activity_log: { timestamp: string; action: string; details?: string }[];
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const sendChatQuery = async (query: string, categories?: string[]): Promise<ChatResponse> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/query`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query,
        categories: categories && categories.length > 0 ? categories : undefined
      }),
    });

    if (!response.ok) {
      throw new Error(`API request failed with status ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Error sending chat query:', error);
    throw error;
  }
};

export const getFolderStatus = async (): Promise<FolderStatus> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/capture/folder/status`);
    if (!response.ok) {
      // Return a default/mock if the endpoint fails (handling dev environment)
      console.warn(`Folder status endpoint failed: ${response.status}`);
      return { file_count: 0, watcher_running: false };
    }
    return await response.json();
  } catch (error) {
    console.error('Error fetching folder status:', error);
    return { file_count: 0, watcher_running: false };
  }
};

export interface SystemStatus {
  status: string;
  uptime_seconds: number;
  components: {
    ollama: boolean;
    qdrant: boolean;
    neo4j: boolean;
    redis: boolean;
  };
  models_loaded: Record<string, boolean>;
  capture_active: boolean;
}

export interface QdrantStats {
  status: string;
  points_count: number;
  vectors_size: number;
  indexed_vectors: number;
}

export const getSystemStatus = async (): Promise<SystemStatus | null> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/system/status`);
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error('Error fetching system status:', error);
    return null;
  }
};

export const getQdrantStats = async (): Promise<QdrantStats | null> => {
  try {
    const response = await fetch('http://localhost:6333/collections/bmo_memories');
    if (!response.ok) return null;
    const data = await response.json();
    return {
      status: data.result?.status || 'unknown',
      points_count: data.result?.points_count || 0,
      vectors_size: data.result?.config?.params?.vectors?.size || 0,
      indexed_vectors: data.result?.indexed_vectors_count || 0,
    };
  } catch (error) {
    console.error('Error fetching Qdrant stats:', error);
    return null;
  }
};

export const getMemoryStats = async (): Promise<MemoryStats> => {
  try {
    const [categoriesRes, timelineRes] = await Promise.all([
      fetch(`${API_BASE_URL}/api/memory/stats/categories`),
      fetch(`${API_BASE_URL}/api/memory/stats/timeline`)
    ]);

    let categories: { name: string; count: number }[] = [];
    if (categoriesRes.ok) {
      const catData = await categoriesRes.json();
      categories = Object.entries(catData)
        .map(([name, count]) => ({ name, count: count as number }))
        .filter(c => c.count > 0)
        .sort((a, b) => b.count - a.count);
    }

    let memoriesToday = 0;
    let memoriesWeek = 0;
    let totalMemories = 0;
    if (timelineRes.ok) {
      const timelineData: { date: string; count: number }[] = await timelineRes.json();
      const today = new Date().toISOString().split('T')[0];
      const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
      
      timelineData.forEach(entry => {
        totalMemories += entry.count;
        if (entry.date === today) {
          memoriesToday = entry.count;
        }
        if (entry.date >= weekAgo) {
          memoriesWeek += entry.count;
        }
      });
    }

    return {
      total_memories: totalMemories,
      memories_today: memoriesToday,
      memories_week: memoriesWeek,
      categories,
      activity_log: []
    };
  } catch (error) {
    console.error('Error fetching memory stats:', error);
    return {
      total_memories: 0,
      memories_today: 0,
      memories_week: 0,
      categories: [],
      activity_log: []
    };
  }
};


export interface ChatSessionSummary {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  preview: string;
}

export interface ChatSessionMessage {
  id: string;
  sender: 'user' | 'bmo';
  text: string;
  timestamp: string;
  confidence?: number;
  processing_time_ms?: number;
  screenshots?: ScreenshotRef[];
}

export interface ChatSessionDetail {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatSessionMessage[];
}

export const listChatSessions = async (limit: number = 50): Promise<ChatSessionSummary[]> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/sessions?limit=${limit}`);
    if (!response.ok) return [];
    return await response.json();
  } catch (error) {
    console.error('Error listing chat sessions:', error);
    return [];
  }
};

export const createChatSession = async (title?: string): Promise<ChatSessionDetail | null> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error('Error creating chat session:', error);
    return null;
  }
};

export const getChatSession = async (sessionId: string): Promise<ChatSessionDetail | null> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`);
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error('Error fetching chat session:', error);
    return null;
  }
};

export const deleteChatSession = async (sessionId: string): Promise<boolean> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}`, {
      method: 'DELETE'
    });
    return response.ok;
  } catch (error) {
    console.error('Error deleting chat session:', error);
    return false;
  }
};

export const addMessageToSession = async (
  sessionId: string,
  sender: 'user' | 'bmo',
  text: string,
  confidence?: number,
  processingTimeMs?: number,
  screenshots?: ScreenshotRef[]
): Promise<ChatSessionMessage | null> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/sessions/${sessionId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sender,
        text,
        confidence,
        processing_time_ms: processingTimeMs,
        screenshots
      })
    });
    if (!response.ok) return null;
    return await response.json();
  } catch (error) {
    console.error('Error adding message to session:', error);
    return null;
  }
};
