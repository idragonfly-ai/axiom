CREATE DATABASE IF NOT EXISTS axiom CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE axiom;

SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS axiom_edges;
DROP TABLE IF EXISTS axiom_aliases;
DROP TABLE IF EXISTS axiom_chunks;
DROP TABLE IF EXISTS axiom_concepts;
DROP TABLE IF EXISTS axiom_sources;
SET FOREIGN_KEY_CHECKS = 1;

-- 1. Generalised source provenance for papers, wiki entries, technical manuals, local notes
CREATE TABLE axiom_sources (
    source_id VARCHAR(128) PRIMARY KEY,
    source_type ENUM('paper', 'wiki', 'local_note', 'technical_doc', 'code', 'prose') NOT NULL,
    title VARCHAR(512) NOT NULL,
    uri VARCHAR(1024) NOT NULL,
    publication_date VARCHAR(64) NULL,
    metadata_json LONGTEXT NULL,
    updated_at DATETIME NOT NULL,
    FULLTEXT INDEX ft_source_search (title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Token-boundary aligned text chunks bound to polymorphic sources
CREATE TABLE axiom_chunks (
    chunk_id VARCHAR(128) PRIMARY KEY,
    source_id VARCHAR(128) NOT NULL,
    chunk_index INT NOT NULL,
    token_count INT NOT NULL,
    text_content LONGTEXT NOT NULL,
    INDEX idx_chunk_source (source_id, chunk_index),
    FULLTEXT INDEX ft_chunk_text (text_content),
    FOREIGN KEY (source_id) REFERENCES axiom_sources(source_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Core convergence graph nodes (methods, datasets, concepts, entities, theorems)
CREATE TABLE axiom_concepts (
    concept_id VARCHAR(128) PRIMARY KEY,
    canonical_name VARCHAR(255) NOT NULL,
    concept_type ENUM('concept', 'method', 'dataset', 'entity', 'theorem') NOT NULL,
    summary_markdown TEXT NOT NULL,
    structured_payload LONGTEXT NOT NULL,
    primary_source_id VARCHAR(128) NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_concept_type (concept_type),
    FULLTEXT INDEX ft_concept_search (canonical_name, summary_markdown),
    FOREIGN KEY (primary_source_id) REFERENCES axiom_sources(source_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Alias mapping for variant normalization (qwen3.6 vs qwen_3_6 vs qwen 3.6)
CREATE TABLE axiom_aliases (
    alias_id INT AUTO_INCREMENT PRIMARY KEY,
    concept_id VARCHAR(128) NOT NULL,
    alias_text VARCHAR(255) NOT NULL,
    INDEX idx_alias_text (alias_text),
    UNIQUE KEY uq_concept_alias (concept_id, alias_text),
    FOREIGN KEY (concept_id) REFERENCES axiom_concepts(concept_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Directed semantic edges with source provenance trace
CREATE TABLE axiom_edges (
    edge_id INT AUTO_INCREMENT PRIMARY KEY,
    source_concept_id VARCHAR(128) NOT NULL,
    target_concept_id VARCHAR(128) NOT NULL,
    relation_type VARCHAR(64) NOT NULL,
    context_snippet TEXT NULL,
    confidence_weight FLOAT DEFAULT 1.0,
    source_reference_id VARCHAR(128) NULL,
    INDEX idx_edge_source (source_concept_id),
    INDEX idx_edge_target (target_concept_id),
    FOREIGN KEY (source_concept_id) REFERENCES axiom_concepts(concept_id) ON DELETE CASCADE,
    FOREIGN KEY (target_concept_id) REFERENCES axiom_concepts(concept_id) ON DELETE CASCADE,
    FOREIGN KEY (source_reference_id) REFERENCES axiom_sources(source_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS axiom_queue (
    queue_id INT AUTO_INCREMENT PRIMARY KEY,
    query_text VARCHAR(255) NOT NULL,
    requested_type VARCHAR(64) NULL,
    uri VARCHAR(1024) NULL,
    status ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_queue_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

