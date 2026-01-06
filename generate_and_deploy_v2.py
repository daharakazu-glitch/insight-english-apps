
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

def clean_text(text):
    # Remove "Tip" or other garbage common in these PDFs
    return text.strip()

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
             # Try to find prefix. If multiple, it's tricky, but let's assume valid sentence.
             # Use a window to avoid matching random words appearing before
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

def parse_chapter_text(text):
    lines = text.split('\n')
    items = []
    
    current_item = {}
    state = "FIND_ID" 
    
    def save_current():
        if current_item.get('id') and current_item.get('en_full'):
            q = current_item.get('question', '')
            f = current_item.get('en_full', '')
            ans = find_answer_part(q, f)
            
            if ans and ans in f:
                current_item['answer'] = ans
                current_item['en'] = f.replace(ans, f"{{{ans}}}")
            else:
                 # heuristic fallback: if no blanks detected, maybe sentence is answer?
                 # Or just use the full sentence
                 current_item['answer'] = "???"
                 current_item['en'] = f
            
            expl = "\n".join(current_item.get('explanation_lines', [])).strip()
            current_item['explanation'] = expl
            
            cleanup = {k:v for k,v in current_item.items() if k in ['id', 'ja', 'en', 'answer', 'explanation']}
            items.append(cleanup)

    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # ID detection: 
        # "1056" or "1056-1" or "1-1" or "2"
        # Must be careful not to match simple numbers inside text.
        # We assume ID is usually on its own line or at start of line
        id_match = re.match(r'^(\d+(-\d+)?)$', line)
        
        if id_match:
            # If we are already building an item:
            # 1. It could be the START of a NEW item.
            # 2. It could be the REPEAT of the CURRENT ID (looking for full sentence).
            
            matched_id = id_match.group(1)
            
            if current_item and current_item.get('id') == matched_id:
                # It is the repeated ID!
                # Check if there is text on this line
                content = line[len(matched_id):].strip()
                if len(content) > 5 and not is_japanese(content):
                    # Case A: ID and Sentence on same line (Chapter 24)
                    current_item['en_full'] = content
                    state = "EXPLANATION"
                    continue
                else:
                    # Case B: ID is alone, Sentence is on next lines (Chapter 1)
                    state = "POST_ID_SEARCH"
                    continue
            
            # Start NEW item
            if current_item:
                save_current()
            
            current_item = {
                'id': matched_id,
                'explanation_lines': [],
                'ja': '',
                'question': ''
            }
            state = "JAPANESE"
            continue
            
        if not current_item: continue
        
        if state == "JAPANESE":
            # Skip "Words to Use", "基本", "Tip"
            if line.startswith("Words to Use") or line == "基本":
                continue
            
            if is_japanese(line):
                # Accumulate Japanese text (sometimes multiline?)
                if current_item['ja']:
                     current_item['ja'] += " " + line
                else:
                     current_item['ja'] = line
            
            elif '(' in line or '（' in line:
                # English question found
                current_item['question'] = line
                state = "WAITING_FOR_FULL_SENTENCE"
            else:
                pass

        elif state == "WAITING_FOR_FULL_SENTENCE":
            # In this state, we might see garbage before the ID repeats
            # or we might see the ID repeat.
            # We assume ID detection block above handles the transition.
            # We just ignore stuff here unless it looks like valid English continuation?
            pass

        elif state == "POST_ID_SEARCH":
            # We found the repeated ID, now looking for the English sentence.
            # Skip "F 023" type codes
            if re.match(r'^F\s*\d+', line) or line.startswith("Tip"):
                continue
            
            # If line is Japanese, it's not the English sentence.
            if is_japanese(line):
                continue
                
            # Assume first English/valid line is the sentence
            if len(line) > 2:
                current_item['en_full'] = line
                state = "EXPLANATION"
        
        elif state == "EXPLANATION":
             # Stop if we hit a known "Tip" block if it's just noise, 
             # but often Tip is part of explanation.
             # But "Tip" usually appears BEFORE the breakdown in Chapter 1?
             # In Chapter 1: 
             # ...
             # My father often shops online.
             # ▶ explanation...
             # shop online ...
             
             # In Chapter 24:
             # explanation...
             # 1057 ... (New ID)
             
             # Just collect everything.
             # Filter out "Words to Use" if valid start
             if line == "Words to Use": continue
             current_item['explanation_lines'].append(line)

    if current_item:
        save_current()
        
    return items

def generate_app(chapter_num, items):
    if not TEMPLATE_FILE.exists():
         print("Error: template.html not found")
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
    print("--- Insight App Generator V2.1 (Unified) ---")
    setup_directories()
    
    files = list(PDF_DIR.glob("*.pdf"))
    files.sort(key=lambda x: get_chapter_number(x.name))
    
    generated_links = []
    
    for pdf_file in files:
        print(f"Processing {pdf_file.name}...")
        raw_text = extract_text_pypdf(pdf_file)
        
        items = parse_chapter_text(raw_text)
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
    run_command('git commit -m "Update parsing logic to fix incomplete chapters"', cwd=os.getcwd())
    run_command("git push origin main", cwd=os.getcwd())
    print("Done!")

if __name__ == "__main__":
    main()
