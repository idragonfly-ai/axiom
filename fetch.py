### fetch.py
import os
import sys
import argparse
import urllib.request
import urllib.parse
import bz2
import xml.etree.ElementTree as ET
import time
import json
from html import unescape

WIKI_DUMP_URL = "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2"
ARXIV_OAI_URL = "http://export.arxiv.org/oai2?verb=ListRecords&metadataPrefix=arXiv"
ARXIV_OAI_RESUME_URL = "http://export.arxiv.org/oai2?verb=ListRecords&resumptionToken={token}"

def stream_download(url, dest_path):
    print(f"Downloading stream: {url} -> {dest_path}")
    req = urllib.request.Request(url, headers={'User-Agent': 'AxiomBulkKB/2.0 (local heavy research ingest)'})
    with urllib.request.urlopen(req) as resp, open(dest_path, 'wb') as out_f:
        while True:
            chunk = resp.read(1048576)
            if not chunk:
                break
            out_f.write(chunk)

def get_local_tag(elem_tag):
    if '}' in elem_tag:
        return elem_tag.split('}', 1)[1]
    return elem_tag

def parse_wikipedia_bz2(dump_path, output_jsonl_path, max_articles=None):
    print(f"Streaming parse of Wikipedia bz2 dump: {dump_path}")
	    count = 0
    with bz2.open(dump_path, 'rb') as bz_f, open(output_jsonl_path, 'w', encoding='utf-8') as out_f:
        context = ET.iterparse(bz_f, events=('end',))
        for event, elem in context:
            if get_local_tag(elem.tag) == 'page':
                title_elem = None
                ns_elem = None
                revision = None
                for child in elem:
                    ltag = get_local_tag(child.tag)
                    if ltag == 'title':
                        title_elem = child
                    elif ltag == 'ns':
                        ns_elem = child
                    elif ltag == 'revision':
                        revision = child

                is_main_ns = False
                if ns_elem is not None and ns_elem.text == '0':
                    is_main_ns = True

                title = title_elem.text if title_elem is not None and title_elem.text else ''

                text_content = ''
                if revision is not None:
                    for r_child in revision:
                        if get_local_tag(r_child.tag) == 'text':
                            if r_child.text:
                                text_content = r_child.text
                            break

                if is_main_ns and title and text_content.strip():
                    record = {
                        'source_type': 'wiki',
                        'title': title,
                        'uri': f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                        'text': f"{title}\n\n{text_content}"
                    }
                    out_f.write(json.dumps(record, ensure_ascii=False) + '\n')
                    count += 1
                    if max_articles and count >= max_articles:
                        print(f"Reached max article limit ({max_articles}). Stopping wiki parse.")
                        elem.clear()
                        break
            elem.clear()
    print(f"Extracted {count} full English Wikipedia articles to {output_jsonl_path}")

def harvest_arxiv_bulk_oai(output_jsonl_path, max_records=None, from_date=None):
    print(f"Starting bulk arXiv OAI-PMH harvest -> {output_jsonl_path}")
    url = ARXIV_OAI_URL
    if from_date:
        url += f"&from={from_date}"

    count = 0
    req_headers = {'User-Agent': 'AxiomBulkKB/2.0 (local bulk harvest)'}

    with open(output_jsonl_path, 'w', encoding='utf-8') as out_f:
        while url:
            print(f"Requesting OAI endpoint: {url}")
            req = urllib.request.Request(url, headers=req_headers)
            try:
                with urllib.request.urlopen(req) as resp:
                    xml_data = resp.read()
            except Exception as e:
                print(f"OAI request error: {e}. Retrying in 5 seconds...")
                time.sleep(5.0)
                continue

            root = ET.fromstring(xml_data)
            records = [elem for elem in root.iter() if get_local_tag(elem.tag) == 'record']
            
            for rec in records:
                header = None
                metadata = None
                for child in rec:
                    ltag = get_local_tag(child.tag)
                    if ltag == 'header':
                        header = child
                    elif ltag == 'metadata':
                        metadata = child

                status = ''
                if header is not None:
                    status = header.attrib.get('status', '')
                if status == 'deleted':
                    continue

                clean_id = f"unknown_{count}"
                if header is not None:
                    for h_child in header:
                        if get_local_tag(h_child.tag) == 'identifier' and h_child.text:
                            raw_id = h_child.text.split(':')[-1]
                            clean_id = raw_id.split('v')[0]
                            break

                if metadata is None:
                    continue

                arxiv_record = None
                for m_child in metadata:
                    arxiv_record = m_child
                    break

                title = ''
                abstract = ''
                pub_date = ''

                if arxiv_record is not None:
                    for a_child in arxiv_record.iter():
                        ltag = get_local_tag(a_child.tag)
                        if ltag == 'title' and a_child.text:
                            title = ' '.join(a_child.text.split())
                        elif ltag == 'abstract' and a_child.text:
                            abstract = ' '.join(a_child.text.split())
                        elif ltag == 'created' and a_child.text:
                            pub_date = a_child.text

                if title or abstract:
                    rec_out = {
                        'source_type': 'paper',
                        'title': title or clean_id,
                        'uri': f"https://arxiv.org/abs/{clean_id}",
                        'publication_date': pub_date,
                        'text': f"Title: {title}\nAbstract: {abstract}"
                    }
                    out_f.write(json.dumps(rec_out, ensure_ascii=False) + '\n')
                    count += 1
                    if max_records and count >= max_records:
                        print(f"Reached max record limit ({max_records}). Stopping harvest.")
                        return

            resume_token = None
            for elem in root.iter():
                if get_local_tag(elem.tag) == 'resumptionToken' and elem.text and elem.text.strip():
                    resume_token = elem.text.strip()
                    break

            if resume_token:
                url = ARXIV_OAI_RESUME_URL.format(token=urllib.parse.quote(resume_token))
                time.sleep(1.0)
            else:
                break
    print(f"Harvested {count} bulk arXiv records to {output_jsonl_path}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Axiom massive corpus ingestion tool')
    parser.add_argument('--output-dir', default='./axiom_bulk', help='Output storage directory')
    parser.add_argument('--do-wiki', action='store_true', help='Download and stream-parse full enwiki dump')
    parser.add_argument('--do-arxiv-oai', action='store_true', help='Harvest bulk arXiv records via OAI-PMH')
    parser.add_argument('--max-wiki-articles', type=int, default=None, help='Limit wiki articles processed')
    parser.add_argument('--max-arxiv-records', type=int, default=None, help='Limit arXiv OAI records harvested')

    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    if args.do_wiki:
        wiki_bz2 = os.path.join(args.output_dir, 'enwiki-latest-pages-articles.xml.bz2')
        wiki_jsonl = os.path.join(args.output_dir, 'wiki_full_articles.jsonl')
        if not os.path.exists(wiki_bz2):
            stream_download(WIKI_DUMP_URL, wiki_bz2)
        parse_wikipedia_bz2(wiki_bz2, wiki_jsonl, max_articles=args.max_wiki_articles)

    if args.do_arxiv_oai:
        arxiv_oai_jsonl = os.path.join(args.output_dir, 'arxiv_bulk_oai.jsonl')
        harvest_arxiv_bulk_oai(arxiv_oai_jsonl, max_records=args.max_arxiv_records)

    print("Massive fetch pipeline complete.")
