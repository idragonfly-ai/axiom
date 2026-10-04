import os
import glob
import argparse
import json
import pymysql
from code_parser import ingest_repository_sandbox

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'axiom.json')
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

db_cfg = config['database']
db = pymysql.connect(
    host=db_cfg['host'],
    user=db_cfg['user'],
    password=db_cfg['password'],
    database=db_cfg['database'],
    charset=db_cfg['charset']
)

def extract_text_from_json_object(obj):
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for k in ['text', 'content', 'abstract', 'description', 'body']:
            if k in obj and isinstance(obj[k], str):
                return obj[k]
        return "\n".join(str(v) for v in obj.values() if isinstance(v, (str, int, float)))
    return str(obj)

def parse_file_content(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    full_text_parts = []
    
    if ext in ['.md', '.txt']:
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                full_text_parts.append(f.read())
        except Exception:
            pass
    elif ext == '.jsonl':
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        t = extract_text_from_json_object(obj)
                        if t.strip():
                            full_text_parts.append(t)
                    except Exception:
                        continue
        except Exception:
            pass
    elif ext == '.json':
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        t = extract_text_from_json_object(item)
                        if t.strip():
                            full_text_parts.append(t)
                elif isinstance(data, dict):
                    t = extract_text_from_json_object(data)
                    if t.strip():
                        full_text_parts.append(t)
        except Exception:
            pass
            
    return "\n\n".join(full_text_parts)

def chunk_text_sliding(text, chunk_size=1000, overlap=100):
    chunks = []
    start = 0
    length = len(text)
    idx = 0
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append((idx, text[start:end]))
        start += (chunk_size - overlap)
        idx += 1
    return chunks

def ingest_directory(root_dir, source_type='local_note', chunk_size=1000, overlap=100, is_code_repo=False):
    if is_code_repo:
        ingest_repository_sandbox(root_dir, source_type=source_type, chunk_size=chunk_size, overlap=overlap)
        return

    patterns = [
        os.path.join(root_dir, '**', '*.md'),
        os.path.join(root_dir, '**', '*.txt'),
        os.path.join(root_dir, '**', '*.json'),
        os.path.join(root_dir, '**', '*.jsonl')
    ]
    file_paths = []
    for p in patterns:
        file_paths.extend(glob.glob(p, recursive=True))
        
    with db.cursor() as cur:
        for filepath in file_paths:
            content = parse_file_content(filepath)
            if not content.strip():
                continue
            
            rel_path = os.path.relpath(filepath, root_dir)
            source_id = db.escape_string(rel_path.lower().replace(os.sep, '_').replace('.', '_'))
            safe_type = db.escape_string(source_type)
            safe_title = db.escape_string(os.path.basename(filepath))
            safe_uri = db.escape_string(filepath)
            
            cur.execute(f"""
                INSERT INTO axiom_sources (source_id, source_type, title, uri, publication_date, metadata_json, updated_at)
                VALUES ('{source_id}', '{safe_type}', '{safe_title}', '{safe_uri}', NULL, '{{}}', NOW())
                ON DUPLICATE KEY UPDATE title='{safe_title}', updated_at=NOW()
            """)
            
            cur.execute(f"DELETE FROM axiom_chunks WHERE source_id = '{source_id}'")
            
            chunks = chunk_text_sliding(content, chunk_size=chunk_size, overlap=overlap)
            for c_idx, c_text in chunks:
                chunk_id = db.escape_string(f"{source_id}_chunk_{c_idx}")
                safe_text = db.escape_string(c_text)
                t_count = len(c_text.split())
                cur.execute(f"""
                    INSERT INTO axiom_chunks (chunk_id, source_id, chunk_index, token_count, text_content)
                    VALUES ('{chunk_id}', '{source_id}', {c_idx}, {t_count}, '{safe_text}')
                """)
    db.commit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Axiom multi-format corpus chunker')
    parser.add_argument('--dir', required=True, help='Root directory or Git repository containing source files')
    parser.add_argument('--source-type', default='local_note', choices=['paper', 'wiki', 'local_note', 'technical_doc'], help='Source classification type')
    parser.add_argument('--chunk-size', type=int, default=1000, help='Character window chunk size')
    parser.add_argument('--overlap', type=int, default=100, help='Overlap size between chunks')
    parser.add_argument('--code-repo', action='store_true', help='Treat target directory as a multi-language code repository using code_parser submodule')
    
    args = parser.parse_args()
    ingest_directory(args.dir, source_type=args.source_type, chunk_size=args.chunk_size, overlap=args.overlap, is_code_repo=args.code_repo)
    db.close()
    print("Ingestion complete.")
