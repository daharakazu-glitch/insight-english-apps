
import os
import re
import sys
import json
import subprocess
import unicodedata
from pathlib import Path
from pypdf import PdfReader

# Configuration
PDF_DIR = Path("pdfs")
DOCS_DIR = Path("docs")
TEMPLATE_FILE = Path("template.html")

def run_command(command, cwd=None):
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {command}")
        return None

def setup_directories():
    if not DOCS_DIR.exists():
        DOCS_DIR.mkdir()

def extract_text_pypdf(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")
        return ""

def is_japanese(text):
    for char in text:
        if "HIRAGANA" in unicodedata.name(char, "") or "CJK" in unicodedata.name(char, ""):
            return True
    return False

def find_answer_part(question, full_sentence):
    # Normalize
    q = re.sub(r'\s+', ' ', question).strip()
    f = re.sub(r'\s+', ' ', full_sentence).strip()
    
    # Locate blanks
    start_match = re.search(r'[\(（]', q)
    end_match = re.search(r'[\)）][^\)）]*$', q)
    
    if not start_match:
        # Fallback: compare strings visually?
        return None
        
    prefix = q[:start_match.start()].strip()
    suffix = ""
    if end_match:
        last_paren_index = -1
        for i, char in enumerate(q):
            if char in [')', '）']:
                last_paren_index = i
        if last_paren_index != -1:
             suffix = q[last_paren_index+1:].strip()

    start_idx = 0
    if prefix:
        try:
             # Find prefix in full sentence
             # Use safe index
             start_idx = f.index(prefix) + len(prefix)
        except ValueError:
             # Fuzzy match?
             pass
    
    end_idx = len(f)
    if suffix:
        try:
             found = f.rfind(suffix)
             if found != -1:
                 end_idx = found
        except ValueError:
             pass
             
    answer = f[start_idx:end_idx].strip()
    # Cleanup answer (punctuation?)
    return answer

def classify_line(line):
    line = line.strip()
    if not line: return "EMPTY", None
    
    # Garbage Filter
    if re.match(r'^Tip', line): return "GARBAGE", None
    if re.match(r'^F\s*\d+', line): return "GARBAGE", None
    if line.startswith("Words to Use") or line == "基本": return "GARBAGE", None
    if re.match(r'^Chapter\s*\d+', line, re.IGNORECASE): return "GARBAGE", None

    # ID Patterns
    # 1. ID Only: "1056", "1-1", "-1"
    if re.match(r'^(\d+(?:-\d+)?)$', line) or re.match(r'^(-\d+)(?:＝)?$', line):
        return "ID_ONLY", line.split('＝')[0] # Remove ＝ if exists

    # 2. ID + Japanese: "1059 私は..."
    # Must contain Japanese char
    match_id_jp = re.match(r'^(\d+(?:-\d+)?)\s+([^a-zA-Z].*)$', line)
    if match_id_jp and is_japanese(match_id_jp.group(2)):
        return "ID_JAPANESE", (match_id_jp.group(1), match_id_jp.group(2))

    # 3. ID + English: "1059 I felt..." (Answer Line)
    match_id_en = re.match(r'^(\d+(?:-\d+)?)\s+([a-zA-Z].*)$', line)
    if match_id_en:
        return "ID_ENGLISH", (match_id_en.group(1), match_id_en.group(2))

    # Content Patterns
    if '(' in line or '（' in line:
        # Heuristic: mostly English?
        # If it has Japanese, it might be Japanese text with parens.
        # Questions usually have ( ) blanks.
        if re.search(r'[\(（]\s*[\)）]', line): # Empty parens
             return "QUESTION_LINE", line
    
    if is_japanese(line):
        return "JAPANESE_LINE", line
        
    return "ENGLISH_TEXT", line

def parse_lines_v3(text):
    lines = text.split('\n')
    items = []
    
    # State tracking
    current_item = None
    
    # We maintain a list of items.
    # Logic:
    # We Iterate.
    # If we see ID_HEADER (ID_ONLY or ID_JAPANESE):
    #    Start New Item.
    #    If ID_JAPANESE, fill JA.
    #
    # If we see JAPANESE_LINE:
    #    If current_item has no JA, append.
    #    Else, maybe it's part of multi-line JA.
    #
    # If we see QUESTION_LINE:
    #    If current_item, set Q.
    #    If NO current_item (Orphan), CREATE PROVISIONAL ITEM (Id=??).
    #    Link JAPANESE_LINE from *buffer*?
    #
    # If we see ID_ENGLISH:
    #    Find item with this ID.
    #    Set FullEn.
    #    If current_item is Provisional (no ID), and this ID matches proximity, merge.
    #
    # If we see ENGLISH_TEXT:
    #    Likely Explanation if we have a FullEn.
    
    # Buffer for "Floating Japanese" (Japanese lines that appear before a Q/ID)
    japanese_buffer = [] 
    
    for line in lines:
        kind, data = classify_line(line)
        
        if kind == "GARBAGE" or kind == "EMPTY":
            continue

        if kind == "ID_ONLY":
            # Start Item
            if current_item:
                items.append(current_item)
            
            # Use data as ID
            raw_id = data
            # Handle "-1" case (sub-item)
            if raw_id.startswith('-'):
                # Look at previous ID
                if items:
                    prev_id = items[-1]['id']
                    # e.g. prev=1064, this=-1 -> 1064-1?
                    # Or prev=1064, this=-1 -> 1064-1.
                    # Usually "1064" is header, "-1" follows.
                    # We need the parent.
                    base_id = prev_id.split('-')[0]
                    full_id = f"{base_id}{raw_id}"
                    current_item = {'id': full_id, 'ja': '', 'en_full':'', 'question':'', 'expl': []}
                else:
                    # No parent? Just use as is.
                    current_item = {'id': raw_id, 'ja': '', 'en_full':'', 'question':'', 'expl': []}
            else:
                current_item = {'id': raw_id, 'ja': '', 'en_full':'', 'question':'', 'expl': []}
            
            # If we had buffered Japanese, add it?
            # Usually ID comes *before* Japanese.
            japanese_buffer = []

        elif kind == "ID_JAPANESE":
            if current_item:
                items.append(current_item)
            
            # data is (id, jp_text)
            current_item = {'id': data[0], 'ja': data[1], 'en_full':'', 'question':'', 'expl': []}
            japanese_buffer = []

        elif kind == "JAPANESE_LINE":
            # If we have a current item and no Question yet, it's JA.
            if current_item and not current_item['question']:
                current_item['ja'] += (" " + data if current_item['ja'] else data)
            elif current_item and current_item['en_full']:
                # Japanese appearing after Full English? Likely Expl.
                current_item['expl'].append(data) # Explanation can contain Japanese
            else:
                # No current item? Or current item already has Q?
                # Maybe it's a floating Japanese line for the *next* Q (Orphan Q case).
                japanese_buffer.append(data)
                
        elif kind == "QUESTION_LINE":
            if current_item:
                # Check if current item already has Q?
                if current_item['question']:
                    # New Q for same ID? (Rare, or maybe -1 case missed)
                    # Or maybe previous item wasn't closed properly.
                    # Treat as Orphan if we accept multiple Qs.
                    # Let's verify if 'question' is empty.
                    pass
                else:
                    current_item['question'] = data
                    # Should we consume japanese_buffer?
                    # Ideally JA was already added.
                    if not current_item['ja'] and japanese_buffer:
                        current_item['ja'] = " ".join(japanese_buffer)
                        japanese_buffer = []
                    continue

            # ORPHAN Q Handling
            if not current_item or current_item.get('en_full'): # If current is 'done' (has full answer)
                 # Create provisional
                 ja_text = " ".join(japanese_buffer)
                 current_item = {'id': 'PENDING', 'ja': ja_text, 'en_full':'', 'question': data, 'expl': []}
                 japanese_buffer = []
            elif current_item and not current_item['question']:
                 current_item['question'] = data

        elif kind == "ID_ENGLISH":
            # content is (id, text)
            new_id, text = data
            
            # Check if this matches Current Item
            if current_item and current_item['id'] == new_id:
                current_item['en_full'] = text
                
            elif current_item and current_item['id'] == 'PENDING':
                # RESOLVE Pending Item
                current_item['id'] = new_id
                current_item['en_full'] = text
                
            else:
                # ID mismatch.
                # Maybe we missed the header?
                # But we have the Answer.
                if current_item: items.append(current_item)
                
                # Start new item with Answer? (No JA/Q?)
                # Wait, if we missed Header, do we have content?
                # If we have buffered Japanese/Q?
                
                # Try to find if we have an Orphan Q in items list? (Unlikely)
                
                # Just create item.
                current_item = {'id': new_id, 'ja': '', 'en_full': text, 'question':'', 'expl': []}
            
            japanese_buffer = []

        elif kind == "ENGLISH_TEXT":
            # Likely Explanation.
            if current_item and current_item['en_full']:
                 current_item['expl'].append(data)
            else:
                 # Maybe part of Q? or part of JA (katakana)?
                 pass

    if current_item:
        items.append(current_item)

    # Post-Process Items
    final_items = []
    for item in items:
        # Validate Valid Item
        if not item['id'] or item['id'] == 'PENDING': continue
        if not item['en_full']: continue 
        # Calculate Answer
        q = item['question']
        f = item['en_full']
        
        # If Q missing, maybe F is enough? (Not ideal)
        if not q:
            ans = "???"
            # Try heuristic?
        else:
            ans = find_answer_part(q, f)
        
        if not ans or ans not in f:
             # Fallback
             ans = f
             item['en'] = f
        else:
             item['answer'] = ans
             item['en'] = f.replace(ans, f"{{{ans}}}")
             item['answer'] = ans # Ensure string
             
        item['explanation'] = "\n".join(item['expl']).strip()
        
        # Cleanup
        final_items.append({
            'id': item['id'],
            'ja': item['ja'],
            'en': item['en'],
            'answer': item.get('answer', '???'),
            'explanation': item['explanation']
        })
        
    return final_items

def generate_app(chapter_num, items):
    if not TEMPLATE_FILE.exists():
         return ""
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()
    
    chapter_title_text = f"Chapter {chapter_num}"
    template = re.sub(r'<title>.*?</title>', f'<title>Insight App - {chapter_title_text}</title>', template)
    template = re.sub(
        r'<h2 id="app-subtitle"([^>]*)>.*?</h2>', 
        f'<h2 id="app-subtitle"\\1>学習用サイト（{chapter_title_text}）</h2>', 
        template
    )
    
    json_data = json.dumps(items, ensure_ascii=False, indent=4)
    start_marker = "const chapterData = ["
    end_marker = "];"
    
    start_idx = template.find(start_marker)
    if start_idx != -1:
         end_idx = template.find(end_marker, start_idx)
         if end_idx != -1:
             new_code = f"const chapterData = {json_data};"
             template = template[:start_idx] + new_code + template[end_idx+2:]
    
    return template

def get_chapter_number(filename):
    normalized = unicodedata.normalize('NFKC', filename)
    match = re.search(r'(\d+)', normalized)
    if match: return int(match.group(1))
    return 999

def main():
    print("--- Insight App Generator V3.0 (Robust) ---")
    setup_directories()
    
    files = list(PDF_DIR.glob("*.pdf"))
    files.sort(key=lambda x: get_chapter_number(x.name))
    
    generated_links = []
    
    for pdf_file in files:
        print(f"Processing {pdf_file.name}...")
        raw_text = extract_text_pypdf(pdf_file)
        
        items = parse_lines_v3(raw_text)
        print(f"Extracted {len(items)} items.")
        
        chap_num = get_chapter_number(pdf_file.name)
        html_content = generate_app(chap_num, items)
        
        output_name = f"chapter-{chap_num:02d}.html"
        output_path = DOCS_DIR / output_name
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        generated_links.append((output_name, f"Chapter {chap_num}"))
        print(f"Saved {output_name}")

    print("Updating Index...")
    index_path = DOCS_DIR / "index.html"
    list_items = ""
    for fname, title in generated_links:
        list_items += f'<li class="mb-2"><a href="{fname}" class="text-blue-600 hover:underline">{title}</a></li>'
    
    index_html = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Insight English Apps Index</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 p-8">
        <div class="max-w-xxl mx-auto bg-white p-8 rounded shadow">
            <h1 class="text-3xl font-bold mb-6">Insight English Apps</h1>
            <ul class="list-disc pl-5">
                {list_items}
            </ul>
        </div>
    </body>
    </html>
    """
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)

    print("Deploying...")
    run_command("git add .")
    run_command('git commit -m "Update parsing logic V3 (Robust)"', cwd=os.getcwd())
    run_command("git push origin main", cwd=os.getcwd())

if __name__ == "__main__":
    main()
