An enterprise-grade, stateful **Agentic Retrieval-Augmented Generation (RAG)** platform designed for mission-critical IT infrastructure, cloud-native environments, and hardware acceleration querying. 

Built with **LangGraph** orchestration, **Qdrant** vector store, **Neon PostgreSQL** durable checkpointers, **Portkey AI** LLM gateway with automated key rotation & failover, **4-stage zero-cost guardrails**, full **Logfire + LangSmith + Prometheus** observability, and **Cilium eBPF** zero-trust network policies on Kubernetes.

---

## 📑 Table of Contents
- [Architecture Overview](#-architecture-overview)
- [Key Features](#-key-features)
- [System Workflow](#-system-workflow)
- [Repository Structure](#-repository-structure)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Environment Configuration](#environment-configuration)
  - [Local Development](#local-development)
  - [Docker Compose Deployment](#docker-compose-deployment)
- [Automated Evaluation Suite (Ragas)](#-automated-evaluation-suite-ragas)
- [Kubernetes & Zero-Trust Security](#-kubernetes--zero-trust-security)
- [Observability & Monitoring](#-observability--monitoring)
- [API Reference](#-api-reference)

---

## 🏛️ Architecture Overview

```mermaid
flowchart TD
    subgraph ClientLayer["🌐 Client & Ingress Layer"]
        UI["🖥️ Streamlit UI Dashboard\n(OAuth 2.0 / Chat / Document Upload)"]
        API_GW["🛡️ NGINX Ingress / TLS Termination\n(Rate Limiting & Proxy Body Control)"]
    end

    subgraph SecurityLayer["🛡️ 4-Stage Multi-Layer Guardrails"]
        S1["Stage 1: Regex Exploit & Attack Blacklist"]
        S2["Stage 2: Intent & Greetings Allowlist"]
        S3["Stage 3: Enterprise Domain Keyword Match (0 Token Cost)"]
        S4["Stage 4: LLM-as-a-Judge Semantic Guardrail (Fail-Closed)"]
    end

    subgraph AgentLayer["🧠 LangGraph Stateful Agent Graph"]
        Planner["📋 Planner Node\n(Query Intent & Deconstruction)"]
        Router{"🔀 Router Condition"}
        Retriever["🔍 Retriever Node\n(Qdrant Hybrid Search)"]
        Responder["✍️ Responder Node\n(Grounded Context Synthesis)"]
    end

    subgraph StorageLayer["🗄️ Persistence & Vector Storage"]
        Qdrant[("⚡ Qdrant Vector DB\n(Payload Indexing & Metadata Filtering)")]
        NeonPostgres[("🐘 Neon PostgreSQL\n(LangGraph Checkpointer / Thread State)")]
    end

    subgraph GatewayLayer["🔌 LLM Gateway & Resiliency"]
        Portkey["🌐 Portkey AI Gateway\n(Semantic Caching & Virtual Keys)"]
        KeyRotator["🔄 Active API Key Rotator"]
        LLM_Primary["⚡ Primary: Groq (Qwen / Llama 3.3 70B)"]
        LLM_Fallback["🛡️ Fallback: Google Gemini 2.5 Flash"]
    end

    subgraph ObservabilityLayer["📊 Telemetry & Observability"]
        Logfire["🔥 Pydantic Logfire Tracing"]
        LangSmith["🦜 LangSmith Run Visualizer"]
        Prometheus["📈 Prometheus Metrics & Health Probes"]
    end

    UI --> API_GW --> S1
    S1 -->|Block Attack| Reject["⛔ Refusal Response"]
    S1 -->|Pass| S2
    S2 -->|Greeting Match| Responder
    S2 -->|Pass| S3
    S3 -->|Domain Match| Planner
    S3 -->|Pass| S4
    S4 -->|Safe| Planner
    S4 -->|Blocked| Reject

    Planner --> Router
    Router -->|Conversational Query| Responder
    Router -->|Domain / Search Query| Retriever

    Retriever <--> Qdrant
    Retriever --> Responder
    Responder <--> Portkey
    Portkey <--> KeyRotator
    KeyRotator --> LLM_Primary
    KeyRotator -.->|On Failure / Rate Limit| LLM_Fallback

    Planner & Retriever & Responder <--> NeonPostgres
    AgentLayer -.-> Logfire & LangSmith & Prometheus
```

---

## ✨ Key Features

### 1. 🧠 Stateful LangGraph Multi-Node Orchestration
- **Conditional Workflow Routing**: Dynamically distinguishes conversational queries from context-heavy inquiries to skip expensive vector lookups.
- **Durable Checkpointing**: Backed by **Neon PostgreSQL** (`PostgresSaver` via `psycopg-pool`) for multi-turn conversational recovery and session management, with automatic fallback to `MemorySaver`.

### 2. 🛡️ 4-Stage Zero-Cost & Semantic Guardrails
- **Stage 1 (Blacklist)**: Instant regex blocking of jailbreaks, prompt injection (`ignore previous instructions`), reverse shells, container escapes, and credential harvesting.
- **Stage 2 (Greetings Allowlist)**: Zero-latency matching for system greetings and capability queries.
- **Stage 3 (Enterprise Domain Match)**: Zero-token keyword routing covering Kubernetes, Linux kernels, eBPF, Cilium, Intel hardware accelerators, and datacenter networking.
- **Stage 4 (LLM Judge Fallback)**: Semantic categorization for ambiguous or adversarial edge cases with fail-closed security.

### 3. 🔄 Resilient Portkey LLM Gateway & Key Rotation
- Virtual key management with unified routing through **Portkey AI**.
- Automatic API key rotation across pool workers to avoid vendor rate limits.
- Intelligent fallback from **Groq** (`llama-3.3-70b-versatile` / `qwen3.6-27b`) to **Google Gemini** (`gemini-2.5-flash`).
- Built-in semantic caching with `x-portkey-cache-status` extraction (`HIT`/`MISS`).

### 4. 📂 Multimodal Document Processing & Vector Search
- Handles **PDF**, **DOCX**, **PPTX**, and **HTML** ingestion using `pdfplumber`, `unstructured-client`, `python-docx`, and `python-pptx`.
- Semantic chunking, deduplication, and hybrid vector storage in **Qdrant** with collection partitioning and metadata filtering.

### 5. 🧪 6-Dimensional Automated Evaluation (Ragas Benchmark)
- Automated evaluation pipeline benchmarking against golden datasets:
  1. **Faithfulness** (Hallucination detection)
  2. **Answer Relevancy**
  3. **Context Precision**
  4. **Context Recall**
  5. **Answer Correctness**
  6. **Tool Selection / Node Correctness**

### 6. ☸️ Kubernetes & Cilium eBPF Zero-Trust Security
- Multi-stage non-root Docker builds for Backend API and Streamlit UI.
- NGINX Ingress definitions with strict proxy timeouts, TLS/SSL cert-manager, and rate-limiting annotations.
- **Cilium Network Policies** enforcing strict L3/L4/L7 egress filtering (restricting API outbound traffic strictly to Postgres `5432` and approved HTTPS endpoints like Stripe / LLM APIs).

---

## 📁 Repository Structure

```text
.
├── .github/
│   └── workflows/
│       ├── ci-cd.yml               # Automated Ruff linting, byte-compilation & Docker build verification
│       └── keep-alive.yml          # Scheduled health monitoring workflow
├── app/
│   ├── agents/
│   │   ├── nodes/
│   │   │   ├── planner.py          # Query deconstruction & routing decisions
│   │   │   ├── retriever.py        # Qdrant context retrieval & metadata enrichment
│   │   │   └── responder.py        # Context-grounded LLM synthesis & citation tracking
│   │   ├── graph.py                # LangGraph state machine & PostgresSaver checkpointer
│   │   └── state.py                # AgentState schema (TypedDict)
│   ├── db/
│   │   └── database.py             # Neon Postgres thread persistence & session CRUD
│   ├── gateway/
│   │   ├── client.py               # Portkey client, fallback provider, & cache inspector
│   │   └── key_manager.py          # Thread-safe Groq/LLM API key rotator
│   ├── guardrails/
│   │   ├── colang_rules.py         # Colang security flow rules
│   │   └── rails.py                # 4-Stage guardrail pipeline
│   ├── ingestion/                  # Multi-format parsers (PDF, DOCX, PPTX, HTML)
│   ├── routers/
│   │   └── threads.py              # Chat thread and history management endpoints
│   ├── services/
│   │   ├── auth.py                 # Google OAuth 2.0 & Session tokens
│   │   ├── document_parser.py      # Async document ingestion orchestrator
│   │   └── retrieval/
│   │       └── qdrant_service.py   # Qdrant vector operations & indexing
│   ├── config.py                   # Pydantic BaseSettings management
│   ├── health.py                   # Kubernetes Liveness/Readiness endpoints (/healthz, /readyz)
│   ├── logging.py                  # Distributed request ID propagation
│   └── main.py                     # FastAPI application entry point & middleware
├── evals/
│   ├── golden_dataset.json         # Ground truth benchmark dataset
│   ├── metrics.py                  # Ragas 6-experiment evaluation execution engine
│   ├── pipeline.py                 # Batch evaluation runners with automated rate cooldowns
│   └── app.py                      # Interactive evaluation dashboard
├── samples/
│   ├── cilium-network-policy.yaml  # eBPF Zero-Trust Kubernetes NetworkPolicy
│   └── production-ingress-service.yaml # Production NGINX Ingress & Service manifests
├── ui/
│   └── streamlit_app.py            # Modern Streamlit UI with streaming & citations
├── Dockerfile.api                  # Production-optimized FastAPI Dockerfile
├── Dockerfile.ui                   # Production-optimized Streamlit Dockerfile
├── docker-compose.yml              # Local multi-service composition
└── requirements.txt                # Production Python dependencies
```

---

## 🚀 Getting Started

### Prerequisites
- **Python**: `3.11+`
- **Docker & Docker Compose**: `20.10+`
- **Vector DB**: [Qdrant Cloud](https://cloud.qdrant.io/) or local Qdrant instance
- **Database**: [Neon PostgreSQL](https://neon.tech/) or standard PostgreSQL instance

---

### Environment Configuration

Create a `.env` file in the root directory:

```ini
# --- CORE LLM KEYS ---
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
GOOGLE_API_KEY=AIzaSy...
PORTKEY_API_KEY=pk-...
PORTKEY_PRIMARY_SLUG=marathon-api

# --- VECTOR DATABASE (QDRANT) ---
QDRANT_CLUSTER_ENDPOINT=https://your-cluster.qdrant.tech:6333
QDRANT_API_KEY=your-qdrant-api-key
QDRANT_COLLECTION=enterprise_rag

# --- PERSISTENCE (POSTGRESQL) ---
NEON_DB_URL=postgresql://user:password@ep-sample-pool.neon.tech/enterprise_rag?sslmode=require

# --- OBSERVABILITY & TRACING ---
LOGFIRE_TOKEN=pylf_...
LOGFIRE_BASE_URL=https://logfire-us.pydantic.dev
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=enterprise-rag-prod

# --- SECURITY & AUTH ---
RAG_API_KEY=your-secure-internal-api-key
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

---

### Local Development

1. **Clone the repository**:
   ```bash
   git clone https://github.com/namangoyal186/enterprise-agentic-rag-kubernetes.git
   cd enterprise-agentic-rag-kubernetes
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   # Linux / macOS:
   source .venv/bin/activate
   # Windows:
   .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Start the FastAPI Backend**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Start the Streamlit UI (in a new terminal)**:
   ```bash
   streamlit run ui/streamlit_app.py --server.port 8501
   ```

---

### Docker Compose Deployment

Run the complete multi-container stack (Backend API + Streamlit Dashboard) with a single command:

```bash
docker compose up --build -d
```

- **Backend API**: `http://localhost:8000` (Swagger Docs at `/docs`)
- **Frontend UI**: `http://localhost:8501`
- **Metrics**: `http://localhost:8000/metrics`
- **Health Checks**: `http://localhost:8000/healthz`

---

## 🧪 Automated Evaluation Suite (Ragas)

To benchmark retrieval and generation quality against the **Golden Dataset**, run the automated test suite:

```bash
python -m evals.run_evals
```

Or launch the interactive evaluation explorer:
```bash
streamlit run evals/app.py --server.port 8502
```

### Evaluated Dimensions:
| Metric | Description | Target Score |
| :--- | :--- | :---: |
| **Faithfulness** | Validates answer claims directly against retrieved chunks (Hallucination check). | `> 0.90` |
| **Answer Relevancy** | Ensures output directly addresses the user query without conversational drift. | `> 0.88` |
| **Context Precision** | Measures signal-to-noise ratio of ranked documents from Qdrant. | `> 0.85` |
| **Context Recall** | Confirms whether ground-truth reference context was successfully retrieved. | `> 0.85` |
| **Tool Correctness** | Evaluates accuracy of planner node routing decisions. | `> 0.95` |

---

## ☸️ Kubernetes & Zero-Trust Security

### 1. Ingress & Service Deployment
Apply the production NGINX Ingress controller configuration with rate-limiting and TLS termination:
```bash
kubectl apply -f samples/production-ingress-service.yaml
```

### 2. Cilium eBPF Network Policies
Enforce zero-trust network boundaries so payment and RAG services can only communicate with authorized endpoints:
```bash
kubectl apply -f samples/cilium-network-policy.yaml
```

```yaml
# Sample snippet from cilium-network-policy.yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: secure-checkout-egress
  namespace: production
spec:
  endpointSelector:
    matchLabels:
      app: checkout
  egress:
    - toEndpoints:
        - matchLabels:
            "k8s:io.kubernetes.pod.namespace": database
            app: postgres-cluster
      toPorts:
        - ports:
            - port: "5432"
              protocol: TCP
```

---

## 📊 Observability & Monitoring

The platform integrates deep telemetry across every layer of execution:
- **Pydantic Logfire**: Distributed span profiling, error captures, token cost aggregation, and Portkey cache status logging.
- **LangSmith**: Detailed visual trace graphs of the LangGraph state machine execution steps.
- **Prometheus Metrics**: Scraped at `/metrics` (request counts, latency histograms, error rates, guardrail block statistics).
- **Health Probes**: 
  - `GET /healthz` - Kubernetes liveness probe
  - `GET /readyz` - Kubernetes readiness probe (validates Qdrant, Postgres & LLM connectivity)

---

## 📡 API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/chat` | Main stateful chat endpoint with LangGraph orchestration. |
| `POST` | `/api/v1/upload` | Multimodal document upload & Qdrant vectorization. |
| `GET` | `/api/v1/threads` | List active chat threads for authenticated user. |
| `GET` | `/api/v1/threads/{id}` | Retrieve historical message state and citations. |
| `GET` | `/healthz` | Kubernetes Liveness Probe. |
| `GET` | `/readyz` | Kubernetes Readiness Probe. |
| `GET` | `/metrics` | Prometheus metrics scrape endpoint. |

---

## 📄 License
Distributed under the MIT License. See `LICENSE` for more information.

---

## 👤 Author
**Naman Goyal**
- GitHub: [@namangoyal186](https://github.com/namangoyal186)
- LinkedIn: [Naman Goyal](https://www.linkedin.com/in/naman-goyal186/)
