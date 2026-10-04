import os
import sys
import shutil
import tempfile
import glob
import argparse
import json
import subprocess
import pymysql

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'axiom.json')
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

db_cfg = config['database']

IGNORED_DIRS = {'.git', '.github', 'node_modules', 'vendor', 'target', 'build', 'dist', '__pycache__'}
TARGET_EXTENSIONS = {
    '.c', '.cpp', '.h', '.hpp', '.rs',
    '.js', '.css', '.html', '.xml', '.php', '.py', '.lua', '.sh',
    '.sql', '.md', '.txt', '.json', '.jsonl'
}

def get_db_connection():
    return pymysql.connect(
        host=db_cfg['host'],
        user=db_cfg['user'],
        password=db_cfg['password'],
        database=db_cfg['database'],
        charset=db_cfg['charset']
    )

def is_ignored_path(path, root_dir):
    rel = os.path.relpath(path, root_dir)
    parts = rel.split(os.sep)
    for part in parts:
        if part in IGNORED_DIRS:
            return True
    return False

def parse_code_content(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ""

def chunk_code_structured(text, chunk_size=1000, overlap=100):
    chunks = []
    lines = text.splitlines()
    current_chunk_lines = []
    current_length = 0
    idx = 0

    for line in lines:
        current_chunk_lines.append(line)
        current_length += len(line) + 1
        if current_length >= chunk_size:
            chunk_text = "\n".join(current_chunk_lines)
            chunks.append((idx, chunk_text))
            idx += 1
            overlap_lines = current_chunk_lines[-int(len(current_chunk_lines) * (overlap / chunk_size)):] if overlap > 0 else []
            current_chunk_lines = overlap_lines
            current_length = sum(len(l) + 1 for l in current_chunk_lines)

    if current_chunk_lines:
        chunk_text = "\n".join(current_chunk_lines)
        if chunk_text.strip():
            chunks.append((idx, chunk_text))

    if not chunks and text.strip():
        chunks.append((0, text))

    return chunks

def ingest_repository_sandbox(source_target, source_type='technical_doc', chunk_size=1000, overlap=100):
    sandbox_dir = tempfile.mkdtemp(prefix='axiom_sandbox_')
    target_dir = sandbox_dir

    try:
        if source_target.startswith('http://') or source_target.startswith('https://') or source_target.endswith('.git'):
            print(f"Cloning repository into sandbox: {source_target}")
            subprocess.run(['git', 'clone', '--depth', '1', source_target, sandbox_dir], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.path.isdir(source_target):
            print(f"Copying local directory into sandbox: {source_target}")
            if os.path.exists(sandbox_dir):
                shutil.rmtree(sandbox_dir)
            shutil.copytree(source_target, sandbox_dir)
        else:
            print(f"Error: Invalid source target '{source_target}'. Must be a Git URL or local directory.")
            return

        file_paths = []
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in TARGET_EXTENSIONS:
                    full_path = os.path.join(root, file)
                    if not is_ignored_path(full_path, target_dir):
                        file_paths.append(full_path)

        db = get_db_connection()
        with db.cursor() as cur:
            for filepath in file_paths:
                content = parse_code_content(filepath)
                if not content.strip():
                    continue

                rel_path = os.path.relpath(filepath, target_dir)
                source_id = db.escape_string(rel_path.lower().replace(os.sep, '_').replace('.', '_'))
                safe_type = db.escape_string(source_type)
                safe_title = db.escape_string(os.path.basename(filepath))
                safe_uri = db.escape_string(filepath)
                meta_json = db.escape_string(json.dumps({'repository_target': source_target, 'relative_path': rel_path}))

                cur.execute(f"""
                    INSERT INTO axiom_sources (source_id, source_type, title, uri, publication_date, metadata_json, updated_at)
                    VALUES ('{source_id}', '{safe_type}', '{safe_title}', '{safe_uri}', NULL, '{meta_json}', NOW())
                    ON DUPLICATE KEY UPDATE title='{safe_title}', metadata_json='{meta_json}', updated_at=NOW()
                """)

                cur.execute(f"DELETE FROM axiom_chunks WHERE source_id = '{source_id}'")

                chunks = chunk_code_structured(content, chunk_size=chunk_size, overlap=overlap)
                for c_idx, c_text in chunks:
                    chunk_id = db.escape_string(f"{source_id}_chunk_{c_idx}")
                    safe_text = db.escape_string(c_text)
                    t_count = len(c_text.split())
                    cur.execute(f"""
                        INSERT INTO axiom_chunks (chunk_id, source_id, chunk_index, token_count, text_content)
                        VALUES ('{chunk_id}', '{source_id}', {c_idx}, {t_count}, '{safe_text}')
                    """)
        db.commit()
        db.close()
        print(f"Successfully ingested {len(file_paths)} files from {source_target}.")

    finally:
        if os.path.exists(sandbox_dir):
            shutil.rmtree(sandbox_dir)
            print("Sandbox successfully cleaned up and destroyed.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Axiom Sandbox Code and Repository Parser Submodule')
    parser.add_argument('--target', required=True, help='Git repository URL or local directory path')
    parser.add_argument('--source-type', default='technical_doc', choices=['paper', 'wiki', 'local_note', 'technical_doc'], help='Source classification type')
    parser.add_argument('--chunk-size', type=int, default=1000, help='Character window chunk size')
    parser.add_argument('--overlap', type=int, default=100, help='Overlap size between chunks')

    args = parser.parse_args()
    ingest_repository_sandbox(args.target, source_type=args.source_type, chunk_size=args.chunk_size, overlap=args.overlap)
