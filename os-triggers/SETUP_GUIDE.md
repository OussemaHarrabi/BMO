# Enhanced Multi-Format RAG Pipeline - Setup Guide

## Architecture Overview

The system now supports **multiple file types** with an intelligent processing pipeline:

### Workflows

#### 1. Text Files (.txt, .md, .docx, .pdf, code files)
```
File → Text Extraction → LLM Summarization → Embedding → Qdrant
```

#### 2. Image Files (.jpg, .png, .gif, etc.)
```
Image → Vision Model (description) → LLM Summarization → Embedding → Qdrant
```

## Setup Instructions

### 1. Qdrant (Already Done ✓)
```bash
docker run -p 6333:6333 qdrant/qdrant
```
- Collection auto-created on startup
- Name: `documents`
- Vector dimension: 384 (default, configurable)

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

**Core libraries:**
- `watchdog` - File system monitoring
- `sentence-transformers` - Text embedding (384-dim vectors)
- `ollama` - Local LLM integration
- `python-docx` - .docx file support
- `PyPDF2` - PDF text extraction

### 3. Install Ollama & Download Models

#### Install Ollama
Visit: https://ollama.ai/download

#### Download Models (max 4B as specified)

**For text summarization:**
```bash
ollama pull llama3.2:3b        # 3B parameters (recommended)
# OR
ollama pull phi3:3.8b          # 3.8B parameters
# OR
ollama pull gemma2:2b          # 2B parameters (faster)
```

**For image description (vision):**
```bash
ollama pull llava-phi3:3.8b    # 3.8B vision model (recommended for 4B limit)
# OR
ollama pull llava:7b           # 7B vision model (higher quality, exceeds 4B)
```

### 4. Configure Models in main.py

Edit [main.py](main.py#L30-L35):

```python
# Vision model for image description
vision = VisionService(model_name="llava-phi3:3.8b")  # Change model here

# LLM for summarization
summarization = SummarizationService(model_name="llama3.2:3b", max_tokens=150)

# Embedding dimension (must match model)
embedding = EmbeddingService(model_name="all-MiniLM-L6-v2", dimension=384)
```

**Embedding model options:**
- `all-MiniLM-L6-v2` → 384 dimensions (default, fast)
- `all-mpnet-base-v2` → 768 dimensions (higher quality)
- `paraphrase-MiniLM-L3-v2` → 384 dimensions (faster)

⚠️ **Important:** If you change embedding dimension, update `QdrantClient(vector_size=...)` to match!

### 5. Set Watch Directory

Edit [main.py](main.py#L10):
```python
DEFAULT_WATCH = "C:\\Users\\YourName\\Documents\\watched_folder"
```

### 6. Run the Pipeline
```bash
python main.py
```

## Supported File Types

### Text Extraction
- Plain text: `.txt`, `.md`, `.log`, `.csv`
- Code: `.py`, `.js`, `.java`, `.cpp`, `.c`, `.h`
- Documents: `.docx` (requires python-docx)
- PDFs: `.pdf` (requires PyPDF2)
- Structured: `.json`, `.xml`

### Image Processing
- Formats: `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.webp`, `.tiff`
- Vision model generates text descriptions
- Descriptions are summarized and embedded

### Unsupported Files
- Stored as **metadata-only** (no embedding)
- Still tracked in Qdrant with file identity

## How It Works

### Text Processing Example
```
1. File created: report.docx
2. Extract text (python-docx)
3. Send to LLM: "Summarize this document..."
4. Get summary: "Quarterly revenue increased 15%..."
5. Generate embedding from summary
6. Store in Qdrant with metadata:
   {
     "file_id": "uuid",
     "summary": "Quarterly revenue...",
     "original_length": 5000,
     "summary_length": 150,
     "content_type": "text"
   }
```

### Image Processing Example
```
1. File created: chart.png
2. Send to vision model (llava-phi3:3.8b)
3. Get description: "Bar chart showing revenue growth..."
4. Send description to LLM for summarization
5. Get summary: "Chart displays Q4 revenue increase..."
6. Generate embedding from summary
7. Store in Qdrant with metadata:
   {
     "file_id": "uuid",
     "description": "Bar chart showing...",
     "summary": "Chart displays...",
     "content_type": "image"
   }
```

## Verification

### 1. Check Qdrant Dashboard
```
http://localhost:6333/dashboard
```
- Navigate to `documents` collection
- Verify points are being created
- Check payloads contain summaries

### 2. Test with Sample Files
```bash
# Create watched folder
mkdir watched_folder

# Add test files
echo "This is a test document about machine learning." > watched_folder/test.txt
# Add an image
copy some_image.jpg watched_folder/
# Add a docx file
copy document.docx watched_folder/
```

Check logs for processing pipeline execution.

## Performance Notes

### Model Sizes
- **Text LLM (3-4B)**: 2-4GB RAM, ~1-2 sec/summary
- **Vision LLM (3.8B)**: 3-5GB RAM, ~3-5 sec/image
- **Embedding model (384-dim)**: ~100MB RAM, <100ms/text

### Recommendations
- Use SSD for better file watching performance
- 8GB+ RAM recommended for running all models
- GPU acceleration (CUDA) speeds up LLM inference 5-10x

## Troubleshooting

### Issue: "ollama not installed"
- Install Ollama from https://ollama.ai/download
- Verify: `ollama list` in terminal

### Issue: "Model not found"
- Pull model: `ollama pull llama3.2:3b`
- Check available: `ollama list`

### Issue: "sentence-transformers not installed"
- Run: `pip install sentence-transformers torch`
- May need: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`

### Issue: "python-docx not installed"
- Run: `pip install python-docx`
- .docx files will be skipped until installed

### Issue: "Zero vectors in Qdrant"
- Check logs for stub mode warnings
- Verify models are loaded: watch startup logs
- Test embedding: `embedding.embed("test")` should return non-zero values

## Architecture Files

- **text_extractor.py** - Multi-format text extraction
- **summarization_service.py** - LLM summarization (max 4B)
- **vision_service.py** - Image description (vision LLM)
- **embedding_service.py** - Vector embeddings
- **document_processor.py** - Enhanced workflow orchestration
- **main.py** - Service wiring and startup

## Next Steps

1. ✅ Qdrant running in Docker
2. ✅ Collection auto-created
3. 🔧 Install Python dependencies
4. 🔧 Install Ollama + download models
5. 🔧 Configure watch path
6. ▶️ Run `python main.py`
7. 🧪 Test with sample files
