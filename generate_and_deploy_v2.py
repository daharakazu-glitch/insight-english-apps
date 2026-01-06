
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
        # Match '1056' or '1056-1' followed by optional text
        # Group 1: ID
        # Group 3: Rest of line
        id_match = re.match(r'^(\d+(-\d+)?)(.*)$', line)
        
        if id_match:
            matched_id = id_match.group(1).strip()
            # If the rest starts with '-', it might be '1-1' where first part '1' matched.
            # But the regex `\d+(-\d+)?` is greedy, so `1-1` should be fully matched by group 1.
            # Example: "1056 The train..." -> ID="1056", Rest=" The train..."
            # Example: "1-1" -> ID="1-1", Rest=""
            
            rest = id_match.group(3).strip()
            
            # Special check: if 'rest' starts with '-' (e.g. line was "1-1"),
            # regex might have parsed "1" as ID and "-1" as rest if greedy failed?
            # Actually standard regex behavior: `\d+(-\d+)?` will try to match `-1`.
            
            # Transition Logic
            if current_item and current_item.get('id') == matched_id:
                # Repeated ID found
                if len(rest) > 5 and not is_japanese(rest):
                    # Start of sentence found on same line (Chapter 24 style)
                    current_item['en_full'] = rest
                    state = "EXPLANATION"
                    continue
                else:
                    # ID alone (Chapter 1 style), Sentence follows
                    state = "POST_ID_SEARCH"
                    continue
            
            # Start NEW item
            # Only if it looks like a valid new ID start.
            # Sometimes random numbers appear in text.
            # But usually we are in "EXPLANATION" state or "FIND_ID".
            
            # If we are in "WAITING_FOR_FULL_SENTENCE" and see a NEW ID, we likely failed the previous item.
            # But we save what we have (it will be filtered out by save_current because en_full is missing).
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
            if line.startswith("Words to Use") or line == "基本":
                continue
            
            if is_japanese(line):
                if current_item['ja']:
                     current_item['ja'] += " " + line
                else:
                     current_item['ja'] = line
            
            elif '(' in line or '（' in line:
                current_item['question'] = line
                state = "WAITING_FOR_FULL_SENTENCE"
            else:
                pass

        elif state == "WAITING_FOR_FULL_SENTENCE":
            pass

        elif state == "POST_ID_SEARCH":
            if re.match(r'^F\s*\d+', line) or line.startswith("Tip"):
                continue
            if is_japanese(line):
                continue
            if len(line) > 2:
                current_item['en_full'] = line
                state = "EXPLANATION"
        
        elif state == "EXPLANATION":
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
    print("--- Insight App Generator V2.2 (Regex Fix) ---")
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
    # Clean check
    run_command("git add .")
    run_command('git commit -m "Fix parsing regression for Chapter 24"', cwd=os.getcwd())
    run_command("git push origin main", cwd=os.getcwd())
    print("Done!")

if __name__ == "__main__":
    main()
