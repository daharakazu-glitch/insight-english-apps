
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
        try:
            name = unicodedata.name(char, "")
            if "HIRAGANA" in name or "KATAKANA" in name or "CJK" in name:
                return True
        except:
            pass
    return False

def find_answer_part(question, full_sentence):
    q = re.sub(r'\s+', ' ', question).strip()
    f = re.sub(r'\s+', ' ', full_sentence).strip()
    
    start_match = re.search(r'[\(（]', q)
    end_match = re.search(r'[\)）][^\)）]*$', q)
    
    if not start_match:
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
             start_idx = f.index(prefix) + len(prefix)
        except ValueError:
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
    return answer

def classify_line(line):
    line = line.strip()
    if not line: return "EMPTY", None
    
    if re.match(r'^Tip', line): return "GARBAGE", None
    if re.match(r'^F\s*\d+', line): return "GARBAGE", None
    if line.startswith("Words to Use") or line == "基本": return "GARBAGE", None
    if re.match(r'^Chapter\s*\d+', line, re.IGNORECASE): return "GARBAGE", None

    # ID Only
    if re.match(r'^(\d+(?:-\d+)?)$', line) or re.match(r'^(-\d+)(?:＝)?$', line):
        return "ID_ONLY", line.split('＝')[0]

    # ID + Japanese
    match_id_jp = re.match(r'^(\d+(?:-\d+)?)\s+([^a-zA-Z].*)$', line)
    if match_id_jp and is_japanese(match_id_jp.group(2)):
        return "ID_JAPANESE", (match_id_jp.group(1), match_id_jp.group(2))

    # ID + English (Answer Line)
    match_id_en = re.match(r'^(\d+(?:-\d+)?)\s+([a-zA-Z"\'].*)$', line)
    if match_id_en:
        return "ID_ENGLISH", (match_id_en.group(1), match_id_en.group(2))

    # Question Detection
    # 1. Contains blanks
    if re.search(r'[\(（].*?[\)）]', line): 
        return "QUESTION_LINE", line
    
    # 2. Japanese
    if is_japanese(line):
        return "JAPANESE_LINE", line
        
    # 3. English Text (Potential Question part or Explanation)
    return "ENGLISH_TEXT", line

def parse_lines_v3(text):
    lines = text.split('\n')
    items = []
    current_item = None
    japanese_buffer = [] 
    english_buffer = [] # Buffer for multi-line English/Questions
    
    for line in lines:
        kind, data = classify_line(line)
        
        if kind == "GARBAGE" or kind == "EMPTY":
            continue

        if kind == "ID_ONLY":
            if current_item: items.append(current_item)
            
            raw_id = data
            if raw_id.startswith('-'):
                if items:
                    prev_id = items[-1]['id']
                    if 'PENDING' not in prev_id:
                        base_id = prev_id.split('-')[0]
                        raw_id = f"{base_id}{raw_id}"
            
            current_item = {'id': raw_id, 'ja': '', 'en_full':'', 'question':'', 'expl': []}
            if japanese_buffer:
                 current_item['ja'] = " ".join(japanese_buffer)
                 japanese_buffer = []

        elif kind == "ID_JAPANESE":
            if current_item: items.append(current_item)
            current_item = {'id': data[0], 'ja': data[1], 'en_full':'', 'question':'', 'expl': []}
            if japanese_buffer:
                current_item['ja'] = " ".join(japanese_buffer) + " " + current_item['ja']
                japanese_buffer = []

        elif kind == "JAPANESE_LINE":
            if current_item and not current_item['question'] and not current_item['en_full']:
                current_item['ja'] += (" " + data if current_item['ja'] else data)
            elif current_item and current_item['en_full']:
                current_item['expl'].append(data)
            else:
                japanese_buffer.append(data)
                english_buffer = [] # Reset English buffer if new JA starts
                
        elif kind == "QUESTION_LINE":
            if current_item and current_item['en_full']:
                if current_item: items.append(current_item)
                ja_text = " ".join(japanese_buffer)
                current_item = {'id': 'PENDING', 'ja': ja_text, 'en_full':'', 'question': data, 'expl': []}
                japanese_buffer = []
            
            elif current_item:
                if current_item['question']:
                     current_item['question'] += " " + data
                else:
                    current_item['question'] = data
                    if not current_item['ja'] and japanese_buffer:
                        current_item['ja'] = " ".join(japanese_buffer)
                        japanese_buffer = []
            else:
                ja_text = " ".join(japanese_buffer)
                current_item = {'id': 'PENDING', 'ja': ja_text, 'en_full':'', 'question': data, 'expl': []}
                japanese_buffer = []

        elif kind == "ID_ENGLISH":
            new_id, text = data
            
            if current_item and current_item['id'] == new_id:
                current_item['en_full'] = text
                # Also, if we have english_buffer, maybe it was the Question?
                if english_buffer and not current_item['question']:
                     current_item['question'] = " ".join(english_buffer)
                     english_buffer = []
                
            elif current_item and current_item['id'] == 'PENDING':
                current_item['id'] = new_id
                current_item['en_full'] = text
                if english_buffer and not current_item['question']:
                     current_item['question'] = " ".join(english_buffer)
                     english_buffer = []
                
            else:
                if current_item: items.append(current_item)
                ja_text = " ".join(japanese_buffer)
                q_text = " ".join(english_buffer) if english_buffer else ''
                current_item = {'id': new_id, 'ja': ja_text, 'en_full': text, 'question': q_text, 'expl': []}
                japanese_buffer = []
                english_buffer = []

        elif kind == "ENGLISH_TEXT":
            # If we are in "Explanation Mode" (after Full English), append to Expl
            if current_item and current_item['en_full']:
                 current_item['expl'].append(data)
            
            # If we are building a Question (before Full English)
            else:
                 # It might be a broken Question line OR valid Question without blanks
                 if current_item and current_item['question']:
                      current_item['question'] += " " + data
                 elif current_item:
                      english_buffer.append(data)
                 else:
                      # Orphan English
                      english_buffer.append(data)

    if current_item:
        items.append(current_item)

    final_items = []
    for item in items:
        # Filter Pending
        if not item['id'] or item['id'] == 'PENDING': continue
        if not item['en_full']: continue 
        
        q = item['question']
        f = item['en_full']
        
        # Heuristic: If Q is empty but we have Full Sentence, try to guess unique blanks?
        # NO, user wants to see blanks.
        # If Q is empty, maybe English Buffer was the question?
        # We handled english_buffer above.
        
        # If Q still empty, use a placeholder
        if not q:
            ans = "???"
            item['en'] = f
        else:
            ans = find_answer_part(q, f)
            if not ans:
                # If finding answer failed, maybe Q has no blanks?
                # or formatting issue.
                ans = f
                item['en'] = f
            else:
                item['en'] = f.replace(ans, f"{{{ans}}}")
        
        item['answer'] = ans 
        item['explanation'] = "\n".join(item['expl']).strip()
        item['ja'] = item['ja'].strip()
        
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
    print("--- Insight App Generator V3.3 (Max Robust) ---")
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
    run_command('git commit -m "Update parsing logic V3.3 (Max Robust)"', cwd=os.getcwd())
    run_command("git push origin main", cwd=os.getcwd())

if __name__ == "__main__":
    main()
