<!-- Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
SPDX-License-Identifier: Apache-2.0 -->

# Prizolov RAG Architecture: Corporate Knowledge Engineering 🛡

### 🧩 Concept: From Brain Noise to Grounded Answers
The Prizolov RAG (Retrieval-Augmented Generation) pipeline, developed by **Dm.Andreyanov**, is designed to eliminate AI hallucinations by grounding Large Language Models in verified corporate expertise.

### 🏗 Architecture Layers
1. **Extraction (Prizolov Brain Extractor):** High-fidelity interviews with subject matter experts (SMEs) to capture "tacit knowledge". The result is saved as documents (PDF, Word, Excel, CSV, TXT, Markdown) in the workspace folder.
2. **Chunking:** Documents are split into ~1,000-character fragments with 150-character overlap; pages, sheets and sections keep their location so every answer can cite its source.
3. **Sovereign Index:** Fragments are indexed locally in SQLite full-text search (FTS5, BM25 ranking, prefix stemming for Russian word forms). No external vector service and no cloud storage: the index lives in the same local database as the agents' memory.
4. **Context Retrieval:** The **AI Director** and the researcher/writer agents call the `search_knowledge` tool, receive the most relevant fragments with their sources, and only then generate the answer.

### 🛡 Security & Sovereign AI
Unlike cloud-based RAG solutions, Prizolov Architecture prioritizes **Sovereign AI** principles:
- **Local Indexing:** Documents and the index never leave your machine; only the fragments an agent quotes are sent to the model.
- **Untrusted by default:** Retrieved text is wrapped as data, so instructions hidden inside documents cannot take control of the agents (prompt-injection protection).
- **Zero-Drift Compliance:** Lessons and approved prompt versions keep the AI response consistent with the original expert's style and ethical constraints.

### 🛠 Implementation Guide
1. **Step 1:** Put the expert material into the workspace folder (`PRIZOLOV_WORKSPACE`, default `workspace/`), or upload it through the web interface, the HTTP API (`PUT /v1/inbox/{name}`) or the Telegram bot.
2. **Step 2:** Index it: indexing runs automatically on start and before each search; `/index full` in the chat rebuilds it from scratch.
3. **Step 3:** Ask the agents: the Director retrieves the relevant expert context and answers with references to the source documents.

Technical details: [docs/architecture.md](docs/architecture.md#база-знаний).

---
*Methodology by Dm.Andreyanov | Prizolov.ru*
