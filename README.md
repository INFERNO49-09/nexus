# Nexus - Local LLM Interface

A production-ready local AI assistant with real streaming chat, persistent memory,
autonomous agents, multi-step web research, self-improving skills, and open code integration.

```
-------------------------------------------------------------
|                        Browser UI                           |
|           frontend/index.html  (no build step)              |
------------------------------------------------------------
                           | HTTP / SSE
------------------------------------------------------------
|              FastAPI Backend  :8000                          |
|                                                             |
|  /api/chat       Streaming chat + memory injection         |
|  /api/models     Model catalog + one-click pull            |
|  /api/agents     ReAct agent loop (SSE steps)              |
|  /api/research   Multi-step research (SSE progress)        |
|  /api/memory     ChromaDB vector memory CRUD               |
|  /api/skills     Skill registry + AI refinement            |
|  /api/search     Searx / Brave / DuckDuckGo fallback       |
|  /api/system     Hardware detection + health               |
----------------------------------------------------------
         |                      |
----------------    ----------------------------------
|  Ollama :11434  |    |  ChromaDB + sentence-transformers   |
|                 |    |  ~/.nexus/memory/                  |
|  mistral        |    |  Persistent vector memory          |
|  llama3.1:8b   |    -----------------------------------
|  qwen2.5-coder  |
|  deepseek-r1    |    ------------------------------------
|  ... 270+ more  |    |  Web Search                        |
-----------------    |  Searx (self-hosted) :8080         |
                       |  Brave API (optional)              |
                       |  DuckDuckGo (fallback)             |
                       |  Jina Reader (article extract)     |
                       ------------------------------------
```

---

## Quick Start (3 commands)

```bash
# 1. Clone / place nexus/ folder somewhere
cd ~/nexus

# 2. Install everything
./nexus.sh install

# 3. Start
./nexus.sh start
# Opens http://localhost:8000 automatically
```

---

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Ubuntu 20.04 / Debian 11 | Ubuntu 24.04 LTS |
| Python | 3.10 | 3.12 |
| RAM | 8 GB | 16 GB+ |
| Disk | 15 GB | 50 GB+ |
| GPU | None (CPU mode) | NVIDIA RTX 3060+ 8GB VRAM |

---

## Manual Installation

If you prefer step-by-step control:

### 1. Install Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve          # Start the model server
ollama pull mistral   # Download your first model
```

### 2. Python environment
```bash
cd ~/nexus
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure
```bash
cp .env.example .env
nano .env   # Edit settings (optional - defaults work out of the box)
```

### 4. Run
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# Open: http://localhost:8000
```

---

## Service Management

```bash
./nexus.sh start      # Start in background
./nexus.sh stop       # Stop
./nexus.sh restart    # Restart
./nexus.sh status     # Check if running + list models
./nexus.sh logs       # Tail logs
./nexus.sh dev        # Dev mode with auto-reload
./nexus.sh update     # Update pip dependencies
```

---

## Docker (Full Stack)

Runs Nexus + Ollama + Searx + Nginx in one command:

```bash
docker compose up -d

# Pull a model into the Docker Ollama instance
docker compose exec ollama ollama pull mistral

# View logs
docker compose logs -f nexus

# Stop everything
docker compose down
```

---

## Auto-start on Boot (systemd)

```bash
# Copy the service file
sudo cp scripts/nexus@.service /etc/systemd/system/

# Enable and start (replace YOUR_USERNAME)
sudo systemctl daemon-reload
sudo systemctl enable nexus@YOUR_USERNAME
sudo systemctl start  nexus@YOUR_USERNAME

# Check status
sudo systemctl status nexus@YOUR_USERNAME
```

---

## Web Search Setup

### Option A - Searx (recommended, fully private)
```bash
docker run -d --name searx -p 8080:8080 searxng/searxng
# Already set in .env: SEARX_URL=http://localhost:8080
```

### Option B - Brave Search API
```bash
# Sign up: https://api.search.brave.com (2,000 req/day free)
# Add to .env:
BRAVE_API_KEY=your_key_here
```

### Option C - DuckDuckGo (zero config)
Always-on fallback. No API key needed. Slightly lower quality.

---

## OpenAI-Compatible API

Point any OpenAI-compatible app directly at Ollama:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="nexus",  # any string
)

response = client.chat.completions.create(
    model="mistral",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### VS Code (Continue extension)
```json
// ~/.continue/config.json
{
  "models": [{
    "title": "Nexus",
    "provider": "ollama",
    "model": "mistral",
    "apiBase": "http://localhost:11434"
  }]
}
```

### Neovim (llm.nvim)
```lua
require('llm').setup({
  backend = "ollama",
  model   = "mistral",
  url     = "http://localhost:11434",
})
```

---

## API Reference

All endpoints are documented at `http://localhost:8000/docs` (Swagger UI).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chat` | POST | Blocking chat |
| `/api/chat/stream` | POST | SSE streaming chat |
| `/api/models` | GET | Catalog + installed models |
| `/api/models/pull` | POST | Download a model (SSE progress) |
| `/api/agents/run` | POST | Run autonomous agent (SSE steps) |
| `/api/research/run` | POST | Run deep research (SSE progress) |
| `/api/memory` | GET/POST | List or add memories |
| `/api/memory/search` | POST | Semantic memory search |
| `/api/skills` | GET | List skills |
| `/api/skills/execute` | POST | Execute a skill |
| `/api/search` | GET | Web search |
| `/api/system/status` | GET | Health + Ollama + memory stats |
| `/api/system/hardware` | GET | GPU detection + recommendations |

---

## Project Structure

```
nexus/
-- nexus.sh                 One-command launcher
-- requirements.txt         Python dependencies
-- .env.example             Configuration template
-- docker-compose.yml       Full Docker stack
-- Dockerfile               Backend image
|
-- backend/
|   -- main.py              FastAPI app + lifespan
|   -- core/
|   |   -- config.py        Pydantic settings
|   |   -- logger.py        Structured logging
|   |   -- ollama_client.py     Ollama API wrapper
|   |   -- memory_store.py      ChromaDB vector memory
|   |   -- search_engine.py     Searx/Brave/DDG
|   |   -- skill_registry.py    Agent skill manager
|   |   -- agent_engine.py      ReAct agent loop
|   |   -- research_engine.py   Multi-step researcher
|   -- routers/
|       -- chat.py          Streaming chat + history
|       -- models.py        Model catalog + pull
|       -- memory.py        Memory CRUD
|       -- research.py      Research SSE
|       -- skills.py        Skill CRUD + execute
|       -- agents.py        Agent SSE
|       -- search.py        Web search
|       -- system.py        Status + hardware
|
-- frontend/
|   -- index.html           Full UI (no build step)
|
-- scripts/
|   -- nexus@.service       systemd unit
|   -- nginx.conf           Nginx reverse proxy
|
-- ~/.nexus/                Runtime data (auto-created)
    -- memory/              ChromaDB vector store
    -- skills/              Custom skill .py files
    -- research/            Saved research reports
    -- logs/                Application logs
```

---

## GPU Models by VRAM

| GPU / VRAM | Best Models |
|------------|-------------|
| No GPU / CPU | TinyLlama 1.1B, Phi-3.5 Mini (3.8B) |
| 6-8 GB | Mistral 7B, Llama 3.1 8B |
| 10-12 GB | Mistral 7B, Qwen2.5-Coder 7B, DeepSeek-R1 7B |
| 16-24 GB | Qwen2.5 14B, Mixtral 8x7B |
| 40-80 GB | Llama 3.1 70B, full precision models |

---

## Troubleshooting

**"Cannot connect to Ollama"**
```bash
ollama serve          # Start Ollama
ollama list           # Verify models are installed
curl http://localhost:11434/api/tags  # Test the API
```

**Memory not working**
```bash
# Check ChromaDB installed
python3 -c "import chromadb; print('ok')"
pip install chromadb sentence-transformers
```

**Port 8000 already in use**
```bash
# Edit .env: PORT=8001
# Or kill the process:
lsof -ti:8000 | xargs kill
```

**Slow model responses**
- Use a quantized model: `ollama pull mistral:7b-instruct-q4_0`
- Enable GPU: check `nvidia-smi` is working, Ollama auto-detects CUDA

---

## License

MIT - use, modify, and deploy freely.
