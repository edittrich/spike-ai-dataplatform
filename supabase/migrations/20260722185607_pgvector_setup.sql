-- ===============================================================================
-- Supabase PostgreSQL pgvector Schema & HNSW Index Migration
-- ===============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- Create Vector Embeddings Table for Catalog, Ontology & Semantic Layer
CREATE TABLE IF NOT EXISTS financial.entity_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50) NOT NULL, -- 'table', 'column', 'fibo_class', 'data_product', 'semantic_cube'
    fqn VARCHAR(500) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    content_text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(384) NOT NULL, -- 384-dimensional dense vector
    created_at_utc TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create HNSW Index for sub-millisecond Cosine Similarity Search
CREATE INDEX IF NOT EXISTS idx_entity_embeddings_hnsw 
ON financial.entity_embeddings 
USING hnsw (embedding vector_cosine_ops);

COMMENT ON TABLE financial.entity_embeddings IS 'Vector embeddings store for catalog entities, FIBO ontology classes, and semantic cubes using pgvector 0.8.0 HNSW index.';
