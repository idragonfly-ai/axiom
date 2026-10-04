# Axiom: Multi-Format Corpus and Code Ingestion Pipeline

Axiom is a high-performance, robust data ingestion, chunking, and storage engine built to bridge unstructured textual datasets, documentation, and multi-language source code repositories into a relational MariaDB backend. Designed for seamless integration with downstream machine learning pipelines, retrieval systems, and language model workers, Axiom provides a unified abstraction layer for diverse data sources.

---

## Key Features

- **Multi-Format Document Support:** processes and chunks Markdown, plain text, structured JSON, and line-delimited JSON (JSONL) corpora.
- **Multi-Language Code Repository Parsing:** Safely ingests repositories across a wide array of systems, scripting, web, and database languages with syntax-aware structural chunking.
- **Isolated Sandbox Management:** Automatically provisions secure temporary directories or performs shallow Git clones with guaranteed cleanup via teardown handlers.
- **Database Persistence:** Leverages MariaDB relational schemas (`axiom_sources` and `axiom_chunks`) with direct parameter escaping and relational integrity.
- **Polymorphic Pipeline Architecture:** Fully compatible with asynchronous workers, automated RSS fetchers, and API endpoints without requiring modification to core execution scripts.

---

## Supported Languages and Formats

- **Documentation & Notes:** Markdown (.md), Plain Text (.txt), JSON (.json), JSONL (.jsonl)
- **Systems & Compiled Languages:** C (.c), C++ (.cpp, .h, .hpp), Rust (.rs)
- **Web & Scripting Languages:** JavaScript (.js), CSS (.css), HTML (.html), XML (.xml), PHP (.php), Python (.py), Lua (.lua), Shell Scripts (.sh)
- **Data & Query Languages:** SQL (.sql)

---

## System Architecture

Axiom is organized into modular, decoupled components that work in unison:

1. **`code_parser.py`:** Handles repository sandboxing, file path filtering (ignoring build artifacts, version control directories, and dependencies), language whitelisting, structural chunking, and database persistence.
2. **`chunker.py`:** The primary ingestion orchestrator. It processes standard document corpora or delegates code repository ingestion to the code parser submodule.
3. **`worker.py`:** Background processing script that consumes stored chunks for vectorization, indexing, or model evaluation tasks.
4. **`fetch.py`:** Automated data fetcher that pulls live articles or documentation feeds into the ingestion pipeline.
5. **`api_axiom.php`:** Object-oriented PHP backend providing REST endpoints to query and retrieve stored source chunks.
6. **`axiom.json`:** Central configuration file storing database credentials and connection parameters.

---

## Installation and Setup

### 1. Requirements
- Python 3.8+
- MariaDB / MySQL server
- Required Python packages: `pymysql`

Install dependencies via pip:
```bash
pip install pymysql
2. Database Configuration
Create your MariaDB database and configure your axiom.json file in the project root directory:
Ensure your database contains the required axiom_sources and axiom_chunks tables to support relational storage and full-text retrieval.
Usage Guide
Ingesting Standard Document Corpora
To process and store local Markdown notes, technical documentation, or JSONL training datasets, use chunker.py targeting your directory:
Bash
Download code
Copy code
python chunker.py --dir /path/to/documents --source-type local_note --chunk-size 1000 --overlap 100
Ingesting Code Repositories via Submodule
To ingest a local directory or remote Git repository as a technical documentation source using the isolated sandbox parser, include the --code-repo flag:
Bash
python chunker.py --dir /path/to/codebase --source-type technical_doc --chunk-size 1000 --overlap 100 --code-repo
Alternatively, you can invoke code_parser.py directly for targeted repository processing:
Bash
python code_parser.py --target [https://github.com/organization/repository.git](https://github.com/organization/repository.git) --source-type technical_doc --chunk-size 1000 --overlap 100
Extensibility and Contribution
Axiom is designed for extensibility. New language parsers, chunking strategies, or metadata extractors can be integrated directly into code_parser.py or chunker.py without impacting downstream API consumers or workers, thanks to the polymorphic source abstraction layer.


