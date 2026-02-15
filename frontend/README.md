# 🎮 BMO Frontend

Next.js 14 frontend with a retro gaming-inspired BMO interface for the personal memory assistant.

## Architecture

```
frontend/
├── app/
│   ├── layout.tsx       # Root layout with metadata
│   └── page.tsx         # Main page with dynamic animated background
├── src/
│   ├── components/
│   │   ├── ChatInterface.tsx   # BMO shell & navigation
│   │   ├── ChatView.tsx        # Chat UI & screenshot viewer
│   │   ├── Dashboard.tsx       # Stats & system monitoring
│   │   └── Timeline.tsx        # Memory timeline browser
│   └── services/
│       └── api.ts              # Backend API client
├── Dockerfile           # Production container
├── package.json         # Dependencies
└── tsconfig.json        # TypeScript config
```

---

## Components

### ChatInterface (`ChatInterface.tsx`)
The main BMO shell component that wraps the entire UI:

**Features:**
- Retro gaming console aesthetic
- Navigation tabs (Chat, Dashboard, Timeline)
- Animated blinking eyes
- Category filter buttons
- Responsive design (1400px max-width)
- **Collapsible chat history sidebar**
- **Session management (create, load, delete)**

**Views:**
- `chat` - Query memories, view screenshots, manage chat history
- `dashboard` - System stats, histograms
- `timeline` - Browse memories chronologically

**Chat History Sidebar:**
- Toggle with "▶ History" button on the left
- Lists all previous conversations
- Shows title, preview, and timestamp
- Click to resume any conversation
- Create new conversations with "+ New" button
- Delete conversations with trash icon

**Styling Approach:**
```typescript
// Inline styles for component isolation
const styles = {
  container: {
    maxWidth: '1400px',
    height: '95vh',
    backgroundColor: '#63C5DA',  // BMO teal
    borderRadius: '20px',
    border: '2px solid #4A90A4',
  },
  screenBezel: {
    backgroundColor: '#D6F8D6',  // BMO screen green
    borderRadius: '12px',
  }
}
```

---

### ChatView (`ChatView.tsx`)
Interactive chat interface with screenshot display:

**Features:**
- Message history with user/assistant bubbles
- Real-time loading states
- Screenshot gallery from search results
- Fullscreen screenshot viewer with navigation
- Keyboard support (← → arrows, Escape)
- Category badges on results
- **Automatic session persistence** (messages saved to backend)
- **Session loading** (resume previous conversations)

**Props:**
```typescript
interface ChatViewProps {
  sessionId?: string | null;        // Current session to load/save to
  onSessionUpdate?: () => void;     // Callback when session changes
  onFirstMessage?: (text: string) => void;  // Called on first message (for auto-session creation)
}
```

**Screenshot Viewer:**
- Click any screenshot to expand fullscreen
- Navigate with arrow buttons or keyboard
- Dark overlay backdrop
- Close with Escape or click outside

**State Management:**
```typescript
const [messages, setMessages] = useState<Message[]>([]);
const [isLoading, setIsLoading] = useState(false);
const [screenshots, setScreenshots] = useState<ScreenshotRef[]>([]);
const [fullscreenIndex, setFullscreenIndex] = useState<number | null>(null);
```

---

### Dashboard (`Dashboard.tsx`)
System monitoring and memory statistics:

**Displays:**
- **Memory Stats**: Total memories, today's count, weekly count
- **Qdrant Stats**: Vector count, collection status
- **System Status**: Component health (Ollama, Qdrant, Neo4j, Redis)
- **Category Histogram**: Visual breakdown by category
- **Activity Log**: Recent system events

**Data Fetching:**
```typescript
// Parallel API calls with auto-refresh
useEffect(() => {
  const fetchData = async () => {
    const [status, stats, sysStatus, qStats] = await Promise.all([
      getFolderStatus(),
      getMemoryStats(),
      getSystemStatus(),
      getQdrantStats()
    ]);
    // ...
  };
  fetchData();
  const interval = setInterval(fetchData, 10000); // Refresh every 10s
  return () => clearInterval(interval);
}, []);
```

**Histogram Categories:**
- code, work, research, meetings
- entertainment, shopping, social
- health, studying, creative

---

### Timeline (`Timeline.tsx`)
Chronological memory browser:

**Features:**
- Date-grouped memory display
- Category color coding
- Expandable memory details
- Screenshot previews
- Pagination/infinite scroll

---

## API Client (`services/api.ts`)

### Interfaces

```typescript
interface ChatResponse {
  answer: string;
  confidence: number;
  sources: string[];
  screenshots: ScreenshotRef[];
  processing_time_ms: number;
  intent_detected: string;
  uncertain: boolean;
}

interface ScreenshotRef {
  memory_id: string;
  image_base64: string;
  timestamp?: string;
  source_url?: string;
  category?: string;
}

interface MemoryStats {
  total_memories: number;
  memories_today: number;
  memories_week: number;
  categories: { name: string; count: number }[];
  activity_log: { timestamp: string; action: string; details?: string }[];
}

interface QdrantStats {
  status: string;
  points_count: number;
  vectors_size: number;
  indexed_vectors: number;
}

interface ChatSessionSummary {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  preview: string;
}

interface ChatSessionDetail {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatSessionMessage[];
}

interface ChatSessionMessage {
  id: string;
  sender: 'user' | 'bmo';
  text: string;
  timestamp: string;
  confidence?: number;
  processing_time_ms?: number;
  screenshots?: ScreenshotRef[];
}
```

### API Functions

| Function | Endpoint | Description |
|----------|----------|-------------|
| `sendChatQuery()` | POST `/api/chat/query` | Send natural language query |
| `getFolderStatus()` | GET `/api/capture/folder/status` | Get file watcher status |
| `getSystemStatus()` | GET `/api/system/status` | Get component health |
| `getQdrantStats()` | GET `localhost:6333/collections/...` | Direct Qdrant stats |
| `getMemoryStats()` | GET `/api/memory/stats/*` | Memory statistics |
| `listChatSessions()` | GET `/api/chat/sessions` | List all chat sessions |
| `createChatSession()` | POST `/api/chat/sessions` | Create new session |
| `getChatSession()` | GET `/api/chat/sessions/{id}` | Get session with messages |
| `deleteChatSession()` | DELETE `/api/chat/sessions/{id}` | Delete a session |
| `addMessageToSession()` | POST `/api/chat/sessions/{id}/messages` | Add message to session |

---

## Dynamic Background (`page.tsx`)

The main page features an animated dark background:

**Elements:**
- **Gradient Animation**: 15s cycling gradient shift
- **Floating Orbs**: 4 animated blur orbs
- **Grid Overlay**: Retro perspective grid
- **Stars**: 30 twinkling stars
- **Scanlines**: CRT monitor effect

**CSS Animations:**
```css
@keyframes gradientShift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

@keyframes float {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(30px, -30px); }
}

@keyframes twinkle {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}
```

---

## Color Palette

| Element | Color | Hex |
|---------|-------|-----|
| BMO Body | Teal | `#63C5DA` |
| Screen Background | Light Green | `#D6F8D6` |
| Text/Borders | Dark Teal | `#2F4F4F` |
| Border Accent | Medium Teal | `#4A90A4` |
| Success/Active | Mint | `#00FA9A` |
| Error/Warning | Coral | `#FF5E5E` |
| Page Background | Dark Navy | `#0a0a1a` |

---

## Running Locally

```bash
# Install dependencies
npm install

# Development server
npm run dev

# Production build
npm run build
npm start

# Or via Docker
docker-compose up bmo-frontend
```

**Development**: http://localhost:3000

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | Next.js 14 |
| Language | TypeScript |
| Styling | Inline CSS-in-JS |
| State | React useState/useEffect |
| HTTP Client | fetch API |

---

## Design Philosophy

The BMO interface draws inspiration from the Adventure Time character:
- **Retro Gaming Aesthetic**: Rounded corners, pixel-style borders
- **Playful Color Scheme**: Teal and mint green palette
- **Animated Elements**: Blinking eyes, floating orbs
- **Accessibility**: High contrast text, keyboard navigation
- **Responsive**: Works on desktop and tablet screens
