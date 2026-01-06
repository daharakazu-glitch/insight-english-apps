
import os
import re
import sys
import json
import shutil
import subprocess
import unicodedata
import difflib
from pathlib import Path
from pypdf import PdfReader

# Configuration
PDF_DIR = Path("pdfs")
DOCS_DIR = Path("docs")
TEMPLATE_FILE = Path("template.html")
GITHUB_PAGES_BRANCH = "main"

def run_command(command, cwd=None):
    """Running shell commands with error handling."""
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
        print(e.stderr)
        return None

def setup_directories():
    if not DOCS_DIR.exists():
        DOCS_DIR.mkdir()
    if not PDF_DIR.exists():
        PDF_DIR.mkdir()

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
    """
    Compare Question (with blanks) and Full Sentence to find the answer.
    Question: "The train (a ) ( ) ( ) ( ) 20 minutes late."
    Full: "The train arrived at Tokyo Station 20 minutes late."
    Returns: "arrived at Tokyo Station"
    """
    # Normalize
    q = re.sub(r'\s+', ' ', question).strip()
    f = re.sub(r'\s+', ' ', full_sentence).strip()
    
    # Simple heuristic: Split by the blank part
    # We look for the part of Q before the first '(' and after the last ')'
    
    # Find start index of blank area
    start_match = re.search(r'[\(（]', q)
    end_match = re.search(r'[\)）][^\)）]*$', q)
    
    if not start_match:
        return None # No blanks found
        
    prefix = q[:start_match.start()].strip()
    suffix = ""
    if end_match:
        # The suffix starts after the LAST closing parenthesis in the group
        # But end_match finds the last closing parenthesis
        suffix = q[end_match.end()-1:].strip() 
        # Wait, regex `[\)）][^\)）]*$` matches the last closing paren and everything after.
        # So we take text after that match's start index + 1
        last_paren_index = -1
        for i, char in enumerate(q):
            if char in [')', '）']:
                last_paren_index = i
        if last_paren_index != -1:
             suffix = q[last_paren_index+1:].strip()

    # Now find prefix and suffix in Full Sentence
    # This is tricky because of potential OCR typos or minor differences
    # We will try to find the indices
    
    start_idx = 0
    if prefix:
        # Fuzzy match or exact match? Try exact first.
        try:
             start_idx = f.index(prefix) + len(prefix)
        except ValueError:
             # Fallback: maybe just look for the first few words?
             pass
    
    end_idx = len(f)
    if suffix:
        try:
            # Rfind suffix
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
    # States: FIND_ID, JAPANESE, QUESTION, FULL_SENTENCE, EXPLANATION
    
    # Helper to save current item
    def save_current():
        if current_item.get('id') and current_item.get('en_full'):
            # Calculate answer
            q = current_item.get('question', '')
            f = current_item.get('en_full', '')
            ans = find_answer_part(q, f)
            
            # Formatting en field: "The train {arrived at} Tokyo..."
            # If answer found, replace it in full sentence with {answer}
            if ans and ans in f:
                current_item['answer'] = ans
                current_item['en'] = f.replace(ans, f"{{{ans}}}")
            else:
                 # Fallback if logic fails
                 current_item['answer'] = "???"
                 current_item['en'] = f + " {???}"
            
            # Clean explanation
            expl = "\n".join(current_item.get('explanation_lines', [])).strip()
            current_item['explanation'] = expl
            
            # Remove temporary fields
            cleanup = {k:v for k,v in current_item.items() if k in ['id', 'ja', 'en', 'answer', 'explanation']}
            items.append(cleanup)

    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line: continue
        
        # Check if line is a new ID (Digits only)
        # Sometimes ID is "1056" or "1056-1"
        id_match = re.match(r'^(\d+(-\d+)?)$', line)
        
        if id_match:
            # Start new item
            if current_item:
                save_current()
            current_item = {
                'id': id_match.group(1),
                'explanation_lines': []
            }
            state = "JAPANESE"
            continue
            
        if not current_item: continue
        
        # State Machine Logic
        if state == "JAPANESE":
            # Skip noise like "基本", "Tip" (heuristic: strict Japanese check)
            # If line seems to be the Japanese question
            if is_japanese(line) and len(line) > 2:
                current_item['ja'] = line
                state = "QUESTION"
            elif len(line) < 5 and is_japanese(line): # Likely a tag like "基本"
                pass 
            else:
                # Could be english garbage or tags
                pass
                
        elif state == "QUESTION":
            # Looking for English with parens OR just determining it's the question line
            # Heuristic: Contains '(' or '（' and is mostly ascii/english
            if '(' in line or '（' in line:
                 current_item['question'] = line
                 state = "FULL_SENTENCE"
            else:
                 # Check if we accidentally skipped to Full Sentence (no blanks?)
                 # Or maybe Japanese was multiline?
                 pass

        elif state == "FULL_SENTENCE":
            # Looking for line starting with ID or just the sentence
            # Text often repeats ID: "1056 The train..."
            # Remove ID if present
            if line.startswith(current_item['id']):
                line_content = line[len(current_item['id']):].strip()
                current_item['en_full'] = line_content
                state = "EXPLANATION"
            else:
                # Maybe ID isn't repeated? If it looks like English and matches question start...
                # For now assume ID is usually there as per sample
                # If not, treat as explanation or garbage?
                # Sample showed: "1056 The train arrived..."
                pass
                
        elif state == "EXPLANATION":
             # Collect everything until next ID
             # Skip "Tip" garbage
             if "Tip" in line and len(line) < 20: 
                 pass
             else:
                 current_item['explanation_lines'].append(line)

    # Save last item
    if current_item:
        save_current()
        
    return items


def generate_app(chapter_num, items):
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()
    
    # 1. Update Title and Subtitle
    # "学習用サイト（28章 その他の重要熟語）"
    # Replace (28章...) with (Chapter X)
    # The template has hardcoded title, we should regex replace it
    
    chapter_title_text = f"Chapter {chapter_num}"
    
    # Replace title tag
    template = re.sub(r'<title>.*?</title>', f'<title>Insight App - {chapter_title_text}</title>', template)
    
    # Replace h2 subtitle
    # <h2 id="app-subtitle" ...>学習用サイト（28章 ...）</h2>
    # We replace inner text
    template = re.sub(
        r'<h2 id="app-subtitle"([^>]*)>.*?</h2>', 
        f'<h2 id="app-subtitle"\\1>学習用サイト（{chapter_title_text}）</h2>', 
        template
    )
    
    # 2. Inject Data
    json_data = json.dumps(items, ensure_ascii=False, indent=4)
    # Be careful with substitution if the template uses `const chapterData = [...]`
    # We'll use a direct string replacement of the VARIABLE definition
    
    # Regex to find `const chapterData = [ ... ];` (multiline)
    # Note: The template likely has `const chapterData = [`
    pattern = r'const chapterData = \[\s*\{.*?\}\s*\];'
    # This regex is risky for large matching.
    # Better: find `const chapterData = [` and the closing `];`
    
    start_marker = "const chapterData = ["
    end_marker = "];"
    
    start_idx = template.find(start_marker)
    if start_idx != -1:
         # Find the matching closing bracket? or just next semicolon?
         # Since it's JS, finding the corresponding `];` is safest
         # But simpler: replace the whole block if we can find the range.
         # Let's assume the template provided is clean.
         
         # actually, let's just use string replacement of the example data block
         # or just inject after the marker.
         
         # Find where the array ends.
         # A robust way is to replace everything between `const chapterData = [` and the first `];` that follows.
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
    print("--- Insight App Generator V2 ---")
    setup_directories()
    
    files = list(PDF_DIR.glob("*.pdf"))
    files.sort(key=lambda x: get_chapter_number(x.name))
    
    generated_links = []
    
    for pdf_file in files:
        print(f"Processing {pdf_file.name}...")
        raw_text = extract_text_pypdf(pdf_file)
        
        # Debug: Dump text for first file if needed
        # print(raw_text[:500])
        
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

    # Re-generate Index
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

    # Deploy
    print("Deploying...")
    run_command("git add .")
    run_command('git commit -m "Update apps with V2 parser and new template"')
    run_command("git push origin main")
    
    print("Done!")

if __name__ == "__main__":
    main()
