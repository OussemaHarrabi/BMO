# Configuration Example for Enhanced RAG Pipeline

## Recommended Model Combinations

### Option 1: Balanced (Recommended for 4B limit)
```python
# main.py configuration

# Vision: 3.8B parameters
vision = VisionService(model_name="llava-phi3:3.8b")

# Text LLM: 3B parameters
summarization = SummarizationService(model_name="llama3.2:3b", max_tokens=150)

# Embedding: 384 dimensions (fast)
embedding = EmbeddingService(model_name="all-MiniLM-L6-v2", dimension=384)
qdrant = QdrantClient(vector_size=384)
```

### Option 2: Higher Quality (Exceeds 4B limit)
```python
# Vision: 7B parameters (better quality)
vision = VisionService(model_name="llava:7b")

# Text LLM: 3B parameters
summarization = SummarizationService(model_name="llama3.2:3b", max_tokens=200)

# Embedding: 768 dimensions (better semantic understanding)
embedding = EmbeddingService(model_name="all-mpnet-base-v2", dimension=768)
qdrant = QdrantClient(vector_size=768)  # ⚠️ Must match embedding dimension!
```

### Option 3: Fastest (Lower quality, under 4B)
```python
# Vision: 3.8B parameters
vision = VisionService(model_name="llava-phi3:3.8b")

# Text LLM: 2B parameters (faster)
summarization = SummarizationService(model_name="gemma2:2b", max_tokens=100)

# Embedding: 384 dimensions
embedding = EmbeddingService(model_name="paraphrase-MiniLM-L3-v2", dimension=384)
qdrant = QdrantClient(vector_size=384)
```

## Ollama Installation Commands

### Pull Required Models

```bash
# Text summarization models (pick one)
ollama pull llama3.2:3b       # 3B - recommended
ollama pull phi3:3.8b         # 3.8B - alternative
ollama pull gemma2:2b         # 2B - faster

# Vision models (pick one)
ollama pull llava-phi3:3.8b   # 3.8B - fits 4B limit
ollama pull llava:7b          # 7B - better quality, exceeds limit
```

### Verify Models
```bash
ollama list
```

Expected output:
```
NAME                     ID           SIZE
llama3.2:3b              a80c4f17a... 2.0 GB
llava-phi3:3.8b          5f1d4a3b8... 2.2 GB
```

## Common Adjustments

### Increase Summary Length
```python
summarization = SummarizationService(
    model_name="llama3.2:3b",
    max_tokens=300  # Longer summaries
)
```

### Process More Text Before Truncation
```python
# In document_processor.py _process_text method
summary = self._summarization.summarize(text, max_length=10000)  # Default: 5000
```

### Change Summary Prompt
Edit [summarization_service.py](summarization_service.py):
```python
prompt = f"""Create a detailed summary with key points:

Text:
{text_to_summarize}

Summary with bullet points:"""
```

### Add More File Extensions
Edit [text_extractor.py](text_extractor.py):
```python
if ext in {".txt", ".md", ".log", ".rst", ".yaml", ".yml", ...}:
```

## Performance Tuning

### For Slower Hardware
```python
# Use smaller models
summarization = SummarizationService(model_name="gemma2:2b")
vision = VisionService(model_name="llava-phi3:3.8b")

# Reduce max text length
summary = self._summarization.summarize(text, max_length=3000)
```

### For Faster Processing
```python
# Enable GPU in Ollama (automatic if CUDA available)
# Increase temperature for faster (less careful) generation
summarization = SummarizationService(model_name="llama3.2:3b", max_tokens=100)
```

### Batch Processing (Future Enhancement)
Currently processes files one-by-one. For bulk processing:
```python
# Could add batch embedding in embedding_service.py
vectors = self._model.encode([text1, text2, text3], batch_size=32)
```

## Directory Structure After Setup

```
os_events_detecter/
├── main.py                         # ✏️ Edit: Configure models & watch path
├── requirements.txt                # 📦 Install dependencies
├── SETUP_GUIDE.md                  # 📖 Setup instructions
├── CONFIG_EXAMPLES.md              # 📋 This file
├── ARCHITECTURE.md                 # 📐 Original architecture
│
├── text_extractor.py               # 🆕 Multi-format text extraction
├── summarization_service.py        # 🆕 LLM summarization
├── vision_service.py               # 🆕 Image description
├── embedding_service.py            # ✏️ Enhanced with transformers
├── document_processor.py           # ✏️ Enhanced workflow
│
├── watcher.py                      # File system monitoring
├── event_queue.py                  # Sequential processing
├── identity_service.py             # File identity tracking
├── state_machine.py                # Lifecycle states
├── qdrant_client.py                # Vector DB client
├── reconciliation.py               # Startup sync
├── models.py                       # Data models
│
└── watched_folder/                 # 📁 Default monitored directory
```

## Testing Your Setup

### 1. Test Text Processing
```bash
# Create test file
echo "Artificial intelligence is revolutionizing healthcare through predictive diagnostics and personalized treatment plans." > watched_folder/test.txt
```

Expected log output:
```
[TextExtractor] Extracted plain text from ... (123 chars)
[SummarizationService] Generated summary (input=123 chars, output=45 chars)
[EmbeddingService] Generated embedding (text=45 chars, dim=384)
[DocumentProcessor] Text processed: test.txt (original=123, summary=45)
```

### 2. Test Image Processing
```bash
# Copy an image
copy sample_image.jpg watched_folder/
```

Expected log output:
```
[VisionService] Generated description for sample_image.jpg (250 chars)
[SummarizationService] Generated summary (input=250 chars, output=60 chars)
[EmbeddingService] Generated embedding (text=60 chars, dim=384)
[DocumentProcessor] Image processed: sample_image.jpg (description=250, summary=60)
```

### 3. Verify in Qdrant
```bash
curl http://localhost:6333/collections/documents/points/scroll -X POST -H "Content-Type: application/json" -d '{"limit": 5, "with_payload": true}'
```

Should return points with payloads like:
```json
{
  "file_id": "uuid...",
  "summary": "AI is transforming healthcare...",
  "content_type": "text",
  "original_length": 123
}
```

## Fallback Behavior

The system gracefully degrades if dependencies are missing:

| Missing Component | Behavior |
|-------------------|----------|
| `ollama` not installed | Uses stub mode (truncates text instead of summarizing) |
| LLM model not pulled | Falls back to text truncation |
| `sentence-transformers` not installed | Uses zero vectors (still tracks files) |
| `python-docx` not installed | Skips .docx files |
| `PyPDF2` not installed | Skips .pdf files |
| Qdrant unreachable | Logs errors, continues monitoring |

All files are still tracked for identity even if processing fails.
