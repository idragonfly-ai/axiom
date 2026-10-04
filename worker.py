import os
import json
import re
import urllib.request
import urllib.parse
import pymysql
from chunker import ingest_directory

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'axiom.json')
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

db_cfg = config['database']
llm_cfg = config['llm']

db = pymysql.connect(
    host=db_cfg['host'],
    user=db_cfg['user'],
    password=db_cfg['password'],
    database=db_cfg['database'],
    charset=db_cfg['charset']
)

LLAMA_SERVER_URL = llm_cfg['server_url']
LLAMA_MODEL_NAME = llm_cfg['model']

PROMPT_TEMPLATE = """Synthesize concept/method/entity '{query}' bridging available polymorphic source context.
Return ONLY valid JSON matching this schema:
{{
  "concept_id": "{safe_id}",
  "canonical_name": "{query}",
  "concept_type": "concept|method|dataset|entity|theorem",
  "summary_markdown": "Technical synthesis of the concept.",
  "structured_payload": {{
    "definition": "...",
    "key_properties": [],
    "domain_tags": []
  }},
  "aliases": ["alias_1", "alias_2"],
  "edges": [
    {{
      "target_concept_id": "target_slug_or_id",
      "target_name": "Target Display Name",
      "relation_type": "depends_on|introduces|extends|relates_to",
      "context_snippet": "short supporting text quote",
      "confidence_weight": 0.95
    }}
  ]
}}

Context:
{context_text}
"""

def sanitize_fts_query(q):
    cleaned = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in q)
    return ' '.join(cleaned.split())

def parse_llm_json_response(raw_text):
    text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        text = match.group(1)
    else:
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace != -1:
            text = text[first_brace:last_brace+1]
    return json.loads(text)

def fetch_rag_chunks_for_query(cursor, query_term):
    safe_q = db.escape_string(sanitize_fts_query(query_term))
    if not safe_q.strip():
        return []
    sql = f"""
        SELECT c.text_content, c.source_id, s.source_type, s.title
        FROM axiom_chunks c
        JOIN axiom_sources s ON c.source_id = s.source_id
        WHERE MATCH(c.text_content) AGAINST('{safe_q}' IN NATURAL LANGUAGE MODE)
        LIMIT 3
    """
    try:
        cursor.execute(sql)
        return cursor.fetchall()
    except Exception:
        return []

def synthesize_and_persist(query, uri=None):
    if uri and os.path.exists(uri):
        try:
            is_repo = os.path.isdir(uri) and os.path.exists(os.path.join(uri, '.git'))
            ingest_directory(uri, source_type='technical_doc', chunk_size=1000, overlap=100, is_code_repo=is_repo)
        except Exception:
            pass

    with db.cursor() as cur:
        chunks = fetch_rag_chunks_for_query(cur, query)
        combined_context = "\n---\n".join([f"[Source: {r[1]} ({r[2]} - {r[3]})]\n{r[0]}" for r in chunks]) if chunks else "No direct chunk match; synthesize canonical baseline."
        
        safe_id = query.lower().replace(' ', '_')
        prompt = PROMPT_TEMPLATE.format(query=query, safe_id=safe_id, context_text=combined_context[:4000])
        
        payload = {
            "model": LLAMA_MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }
        req = urllib.request.Request(
            LLAMA_SERVER_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw_content = data['choices'][0]['message']['content']
                parsed = parse_llm_json_response(raw_content)
        except Exception:
            return False

        cid = str(parsed.get('concept_id', safe_id))
        cname = str(parsed.get('canonical_name', query))
        ctype = str(parsed.get('concept_type', 'concept'))
        csum = str(parsed.get('summary_markdown', ''))
        cpay = json.dumps(parsed.get('structured_payload', {}))
        primary_source = chunks[0][1] if chunks else None

        safe_cid = db.escape_string(cid)
        safe_cname = db.escape_string(cname)
        safe_ctype = db.escape_string(ctype)
        safe_csum = db.escape_string(csum)
        safe_cpay = db.escape_string(cpay)
        safe_psource = db.escape_string(primary_source) if primary_source else ''
        psource_val = f"'{safe_psource}'" if primary_source else 'NULL'

        sql_concept = f"""
            INSERT INTO axiom_concepts (concept_id, canonical_name, concept_type, summary_markdown, structured_payload, primary_source_id, updated_at)
            VALUES ('{safe_cid}', '{safe_cname}', '{safe_ctype}', '{safe_csum}', '{safe_cpay}', {psource_val}, NOW())
            ON DUPLICATE KEY UPDATE
                canonical_name='{safe_cname}',
                concept_type='{safe_ctype}',
                summary_markdown='{safe_csum}',
                structured_payload='{safe_cpay}',
                primary_source_id={psource_val},
                updated_at=NOW()
        """
        cur.execute(sql_concept)

        aliases = parsed.get('aliases', [])
        for alias in aliases:
            safe_alias = db.escape_string(str(alias))
            cur.execute(f"""
                INSERT IGNORE INTO axiom_aliases (concept_id, alias_text)
                VALUES ('{safe_cid}', '{safe_alias}')
            """)

        edges = parsed.get('edges', [])
        for edge in edges:
            tid = db.escape_string(str(edge.get('target_concept_id', 'unknown')))
            tname = db.escape_string(str(edge.get('target_name', edge.get('target_concept_id', 'unknown'))))
            rel = db.escape_string(str(edge.get('relation_type', 'related_to')))
            snip = db.escape_string(str(edge.get('context_snippet', '')))
            conf = float(edge.get('confidence_weight', 1.0))

            cur.execute(f"""
                INSERT IGNORE INTO axiom_concepts (concept_id, canonical_name, concept_type, summary_markdown, structured_payload, updated_at)
                VALUES ('{tid}', '{tname}', 'concept', 'Auto-generated stub via edge reference.', '{{}}', NOW())
            """)

            cur.execute(f"""
                INSERT INTO axiom_edges (source_concept_id, target_concept_id, relation_type, context_snippet, confidence_weight, source_reference_id)
                VALUES ('{safe_cid}', '{tid}', '{rel}', '{snip}', {conf}, {psource_val})
            """)

    db.commit()
    return True

def poll_and_process_queue():
    with db.cursor() as cur:
        cur.execute("SELECT queue_id, query_text, requested_type, uri FROM axiom_queue WHERE status = 'pending' LIMIT 5")
        rows = cur.fetchall()
        for row in rows:
            qid, qtext, qtype, quri = row[0], row[1], row[2], row[3]
            cur.execute(f"UPDATE axiom_queue SET status = 'processing', updated_at = NOW() WHERE queue_id = {qid}")
            db.commit()
            
            success = synthesize_and_persist(qtext, uri=quri)
            new_status = 'completed' if success else 'failed'
            cur.execute(f"UPDATE axiom_queue SET status = '{new_status}', updated_at = NOW() WHERE queue_id = {qid}")
            db.commit()

if __name__ == '__main__':
    poll_and_process_queue()
    db.close()
