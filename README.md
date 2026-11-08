# 🎮 BMO - AI Personal Memory System

<div align="center">
  <img src="https://img.shields.io/badge/AI-Personal_Memory-63C5DA?style=for-the-badge" />
  <img src="https://img.shields.io/badge/LLM-Local_Only-00FA9A?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Privacy-First-FF5E5E?style=for-the-badge" />
</div>

> *"Who wants to play video games?"* - BMO

BMO is an **AI-powered personal memory assistant** that continuously captures and indexes your digital life. It watches your screen activity, understands what you're doing through vision AI, and lets you query your memories using natural language. Think of it as a second brain that remembers everything you see on your computer - from code you wrote, articles you read, to Instagram reels you watched.

## ✨ Key Features

- 🖥️ **Automatic Screen Capture** - Intelligent triggers capture screenshots based on your activity (app switches, scrolling, tab changes)
- 🧠 **Vision AI Analysis** - Local LLM analyzes each screenshot to extract context, text, and meaning
- 🔍 **Semantic Search** - Query your memories in natural language ("What was that Python library I looked at yesterday?")
- 📊 **Vector Database** - Qdrant stores embeddings for lightning-fast similarity search
- 🕸️ **Knowledge Graph** - Neo4j builds connections between your memories
- 🎮 **BMO Interface** - Retro gaming-inspired UI that's fun to use
- 🔒 **100% Local** - Everything is processed on your machine, so your data never leaves

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER LAYER                                      │
│   Screen Activity → OS Listener → Smart Triggers → Screenshot Capture       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INGESTION PIPELINE                                 │
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Screenshot │───▶│    Vision    │───▶│    Text      │                   │
│  │   Watcher    │    │   Analysis   │    │   Chunking   │                   │
│  │              │    │  (phi3.5)    │    │              │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                │                             │
│                    ┌───────────────────────────┴───────────────────────┐    │
│                    ▼                                                   ▼    │
│           ┌──────────────┐                                   ┌──────────────┐│
│           │  Embeddings  │                                   │   Category   ││
│           │(nomic-embed) │                                   │ Classifier   ││
│           └──────────────┘                                   └──────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            STORAGE LAYER                                     │
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Qdrant     │    │    Neo4j     │    │    Redis     │                   │
│  │  (Vectors)   │    │   (Graph)    │    │   (Cache)    │                   │
│  │  768-dim     │    │  Relations   │    │   Events     │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RETRIEVAL & CHAT                                   │
│                                                                              │
│  User Query ──▶ Router Agent ──▶ Reasoner Agent ──▶ Verifier Agent          │
│                     │                  │                  │                  │
│                     ▼                  ▼                  ▼                  │
│              Intent Detection    RAG Retrieval    Answer Validation         │
│                                                                              │
│                          Response with Screenshots                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (BMO UI)                                 │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  🎮 BMO Interface                                                      │ │
│  │  ├── Chat View (Query memories, see screenshots)                      │ │
│  │  ├── Dashboard (System stats, Qdrant info, histograms)                │ │
│  │  └── Timeline (Browse memories chronologically)                       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 📁 Project Structure

```
bmo/
├── 📄 README.md                    # This file
├── 📄 docker-compose.yml           # Container orchestration
├── 📄 Dockerfile                   # Backend container
├── 📄 requirements.txt             # Python dependencies
├── 📄 main.py                      # Application entry point
├── 📄 .env                         # Environment configuration
├── 📄 BMO_Architecture.excalidraw  # Architecture diagram
│
├── 📁 api/                         # FastAPI Backend
│   ├── main.py                     # API server & CORS setup
│   └── routes/
│       ├── chat.py                 # /api/chat/* endpoints
│       ├── memory.py               # /api/memory/* endpoints
│       ├── capture.py              # /api/capture/* endpoints
│       └── system.py               # /api/system/* endpoints
│
├── 📁 agents/                      # Multi-Agent System
│   ├── orchestrator.py             # Agent coordination
│   ├── router.py                   # Intent classification
│   ├── reasoner.py                 # RAG & response generation
│   ├── verifier.py                 # Answer validation
│   └── prompts/                    # Agent prompt templates
│
├── 📁 capture/                     # Screen Capture System
│   ├── screenshot_watcher.py       # File watcher & processor
│   └── os_monitor/
│       ├── os_listener.py          # OS event listener
│       ├── watcher.py              # Activity monitoring
│       ├── vision_service.py       # LLM vision analysis
│       ├── text_extractor.py       # OCR & text extraction
│       ├── text_chunker.py         # Smart text chunking
│       ├── summarization_service.py# Content summarization
│       ├── state_machine.py        # Capture state management
│       └── models.py               # Data models
│
├── 📁 core/                        # Core Services
│   └── ollama_client.py            # Ollama LLM client
│
├── 📁 memory/                      # Memory Storage
│   ├── vector_store.py             # Qdrant vector operations
│   ├── knowledge_graph.py          # Neo4j graph operations
│   └── schemas/                    # Data schemas
│
├── 📁 processing/                  # Content Processing
│   ├── classifier.py               # Category classification
│   ├── entity_extractor.py         # Named entity extraction
│   ├── summarizer.py               # Text summarization
│   └── prompts/                    # Processing prompts
│
├── 📁 config/                      # Configuration
│   ├── app.yaml                    # Application settings
│   ├── models.yaml                 # LLM model configs
│   ├── storage.yaml                # Database settings
│   └── triggers.yaml               # Capture trigger rules
│
├── 📁 frontend/                    # Next.js Frontend
│   ├── Dockerfile                  # Frontend container
│   ├── package.json                # Node dependencies
│   ├── app/
│   │   ├── layout.tsx              # Root layout
│   │   └── page.tsx                # Main page (dynamic bg)
│   └── src/
│       ├── components/
│       │   ├── ChatInterface.tsx   # BMO shell component
│       │   ├── ChatView.tsx        # Chat & screenshot viewer
│       │   ├── Dashboard.tsx       # Stats & histograms
│       │   └── Timeline.tsx        # Memory timeline
│       └── services/
│           └── api.ts              # Backend API client
│
└── 📁 tests/                       # Test suite
    └── test_pipeline.py            # Pipeline tests
```

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- [Ollama](https://ollama.ai) installed locally
- 8GB+ RAM recommended

### 1. Clone & Setup

```bash
git clone <repo-url>
cd bmo
cp .env.example .env
```

### 2. Pull Required Models

```bash
ollama pull phi3.5:latest      # Vision & reasoning (3.8B params)
ollama pull nomic-embed-text   # Embeddings (768 dimensions)
```

### 3. Start Services

```bash
docker-compose up -d
```

### 4. Access BMO

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **Qdrant Dashboard**: http://localhost:6333/dashboard
- **Neo4j Browser**: http://localhost:7474

## 🔧 How It Works

### Screen Capture Pipeline

1. **OS Listener** monitors your activity (app switches, scrolling, tab changes)
2. **Smart Triggers** decide when to capture based on configurable rules
3. **Screenshot Watcher** detects new captures in the monitored folder
4. **Vision AI** (phi3.5) analyzes the image and extracts:
   - Text content (OCR)
   - Context description
   - Activity category
   - Key entities
5. **Embeddings** (nomic-embed-text) convert content to 768-dim vectors
6. **Storage** saves to Qdrant (vectors) and Neo4j (relationships)

### Query Pipeline

1. **User Query** enters through chat interface
2. **Router Agent** classifies intent (memory search, general chat, etc.)
3. **Reasoner Agent** performs RAG retrieval from Qdrant
4. **Verifier Agent** validates the response accuracy
5. **Response** includes answer + relevant screenshots

### Supported Capture Triggers

| Trigger | Description |
|---------|-------------|
| `app_switch` | When you switch between applications |
| `tab_return` | When returning to a browser tab |
| `scroll_stop_read` | When you stop scrolling to read |
| `deep_read_dwell` | Extended time on same content |
| `scan_search` | Quick scanning behavior |

## 🎯 Use Cases

- **"What was that article I read about React hooks?"** - Find content by topic
- **"Show me the code I wrote yesterday"** - Time-based retrieval
- **"What Instagram reels did I watch?"** - Social media memory
- **"Find that error message I saw"** - Debug assistance
- **"What meetings did I have this week?"** - Activity summary

## 🛠️ Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Backend | FastAPI (Python) | REST API server |
| Frontend | Next.js 14 (TypeScript) | BMO UI |
| Vision LLM | phi3.5 (3.8B) | Image understanding |
| Embeddings | nomic-embed-text | Vector generation |
| Vector DB | Qdrant | Semantic search |
| Graph DB | Neo4j | Knowledge relationships |
| Cache | Redis | Event bus & caching |
| Containers | Docker Compose | Service orchestration |

## 📊 API Endpoints

### Chat
- `POST /api/chat/query` - Query memories with natural language

### Memory
- `GET /api/memory/stats` - Memory statistics
- `GET /api/memory/{id}` - Get specific memory
- `GET /api/memory/search` - Search memories

### Capture
- `GET /api/capture/folder/status` - Watcher status
- `POST /api/capture/folder/ingest` - Trigger manual ingestion

### System
- `GET /api/system/status` - System health check

## 🔒 Privacy & Security

- **100% Local Processing** - All AI runs on your machine via Ollama
- **No Cloud APIs** - Zero data transmission to external services
- **Your Data, Your Control** - Everything stored locally in Docker volumes
- **Open Source Models** - Transparent, auditable AI models

## 🤝 Contributing

Contributions welcome! Please read our contributing guidelines first.

## 📄 License

MIT License - See LICENSE file for details.

---

<div align="center">
  <b>Built with ❤️ for the hackathon</b>
  <br>
  <i>"I am BMO! I help you remember!"</i>
</div>
