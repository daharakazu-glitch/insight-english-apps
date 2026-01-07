
# V5: Decoupled ID Matching Strategy
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
    # Normalize spaces
    q = re.sub(r'\s+', ' ', question).strip()
    f = re.sub(r'\s+', ' ', full_sentence).strip()
    
    # 1. Try explicit blank detection ((...), (...), or underscores)
    start_match = re.search(r'[\(（]', q)
    if start_match:
        prefix = q[:start_match.start()].strip()
        rest = q[start_match.start():]
        end_match = re.search(r'[\)）](.*)$', rest)
        suffix = end_match.group(1).strip() if end_match else ""
        
        # Use prefix/suffix to find middle
        start_idx = 0
        if prefix:
            try: start_idx = f.index(prefix) + len(prefix)
            except ValueError: pass
        
        end_idx = len(f)
        if suffix:
            try:
                 found = f.rfind(suffix)
                 if found != -1: end_idx = found
            except ValueError: pass
        
        candidate = f[start_idx:end_idx].strip()
        return candidate.replace('(', '').replace(')', '').strip()

    underscore_match = re.search(r'_+', q)
    if underscore_match:
        prefix = q[:underscore_match.start()].strip()
        suffix = q[underscore_match.end():].strip()
        
        start_idx = 0
        if prefix:
             try: start_idx = f.index(prefix) + len(prefix)
             except ValueError: pass
        end_idx = len(f)
        if suffix:
             try:
                 found = f.rfind(suffix)
                 if found != -1: end_idx = found
             except ValueError: pass
        
        return f[start_idx:end_idx].strip()

    # 2. Diff-based fallback (Prefix/Suffix matching)
    # If q is "The woman some flowers." and f is "The woman is watering some flowers."
    # Find longest common prefix
    common_prefix_len = 0
    min_len = min(len(q), len(f))
    for i in range(min_len):
        if q[i] == f[i]: common_prefix_len += 1
        else: break
    
    # Check if prefix ended at a space or full (word boundary)
    # Ideal: q[:prefix] should be valid
    
    # Find longest common suffix
    common_suffix_len = 0
    q_rev = q[::-1]
    f_rev = f[::-1]
    min_len = min(len(q), len(f))
    for i in range(min_len):
        if q_rev[i] == f_rev[i]: common_suffix_len += 1
        else: break
        
    if common_prefix_len > 0 or common_suffix_len > 0:
        # Detected diff
        # Check overlaps
        if common_prefix_len + common_suffix_len < len(f):
             # Extract middle
             middle = f[common_prefix_len : len(f) - common_suffix_len]
             return middle.strip()
             
    return None



def parse_chapter_text_v5(text):
    raw_lines = [l.strip() for l in text.split('\n')]
    
    # 1. Statefully collect blocks by ID
    blocks = []
    current_block = None
    
    for line in raw_lines:
        if not line: continue
        
        # Filter garbage
        if re.match(r'^F\s+\d+$', line): continue
        if line.startswith("Tip"): continue
        if "ʁ" in line or "Ͱ" in line: continue # Filter Mojibake
        if line == "Words to Use": continue
        
        # ID Detection
        id_match = re.match(r'^(\d+(?:-\d+)?)(?:\s+(.*))?$', line)
        
        is_new_id = False
        if id_match:
            pot_id = id_match.group(1)
            pot_content = id_match.group(2) or ""
            
            if re.match(r'^\d+$', pot_content.strip()): # Page numbers line "14 15"
                is_new_id = False
            elif len(pot_id) < 6:
                is_new_id = True
        
        if is_new_id:
            id_str = id_match.group(1)
            content = id_match.group(2) or ""
            
            if current_block:
                blocks.append(current_block)
            
            current_block = { "id": id_str, "lines": [] }
            if content.strip():
                current_block["lines"].append(content.strip())
        else:
            if current_block:
                 current_block["lines"].append(line)
    
    if current_block:
        blocks.append(current_block)

    # 2. Process Blocks
    answers = {}
    questions = {}
    explanations = {}
    
    for block in blocks:
        bid = block['id']
        lines = block['lines']
        full_text = " ".join(lines)
        
        # Classification
        # Answer Block signal: Contains "▶" (Explanation marker) OR is purely English without blanks
        # Question Block signal: Contains "(___)", "基本", "Tip", or Japanese WITHOUT "▶"
        
        is_answer_block = False
        if "▶" in full_text: 
            is_answer_block = True
        elif not is_japanese(full_text) and "___" not in full_text and "(" not in full_text:
            is_answer_block = True
            
        if is_answer_block:
            # Extract Answer Sentence vs Explanation
            ans_lines = []
            expl_lines = []
            seen_arrow = False
            
            for l in lines:
                if "▶" in l:
                    seen_arrow = True
                    # The part before ▶ might be answer?
                    parts = l.split("▶", 1)
                    if parts[0].strip():
                         ans_lines.append(parts[0].strip())
                    expl_lines.append("▶ " + parts[1].strip())
                elif seen_arrow:
                    expl_lines.append(l)
                else:
                    ans_lines.append(l)
            
            # Save
            if bid not in answers:
                answers[bid] = " ".join(ans_lines).strip()
                explanations[bid] = "\n".join(expl_lines).strip()
            # If duplicates (unlikely for matched blocks), ignore or merge?
        else:
            # Question Block
            if bid not in questions:
                questions[bid] = { "lines": lines }
            else:
                questions[bid]["lines"].extend(lines)

    # 3. Assembly
    items = []
    
    all_ids = set(answers.keys()) | set(questions.keys())
    def sort_key(s):
        parts = s.split('-')
        try: return [int(p) for p in parts]
        except: return [9999]
    
    sorted_ids = sorted(list(all_ids), key=sort_key)
    
    for id_str in sorted_ids:
        q_data = questions.get(id_str)
        a_text = answers.get(id_str)
        expl_text = explanations.get(id_str, "")
        
        if not q_data and not a_text: continue
        
        # Prepare Q components
        jp_part = ""
        en_question = ""
        
        if q_data:
            jp_lines = []
            en_lines = []
            for l in q_data['lines']:
                if l == "基本": continue
                if is_japanese(l):
                    jp_lines.append(l)
                else:
                    en_lines.append(l)
            
            jp_part = " ".join(jp_lines)
            en_question = " ".join(en_lines)
            
            # Fallback for splitting mixed raw text?
            # V5 simplification: Trust line classification.
        else:
             jp_part = "???"
             en_question = "???"

        if not a_text: a_text = "???"

        # Target Word
        target_word = "???"
        if en_question != "???" and a_text != "???":
            detected = find_answer_part(en_question, a_text)
            if detected: target_word = detected
            
        parsed_en = a_text
        if target_word!= "???" and target_word in a_text:
             parsed_en = a_text.replace(target_word, f"{{{target_word}}}")
        
        items.append({
            "id": id_str,
            "ja": jp_part,
            "en": parsed_en,
            "answer": target_word,
            "explanation": expl_text,
            "question": en_question
        })
        
    return items



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
    print("--- Insight App Generator V5 (Decoupled Matching) ---")
    setup_directories()
    
    files = list(PDF_DIR.glob("*.pdf"))
    files.sort(key=lambda x: get_chapter_number(x.name))
    
    generated_links = []
    
    for pdf_file in files:
        print(f"Processing {pdf_file.name}...")
        raw_text = extract_text_pypdf(pdf_file)
        
        items = parse_chapter_text_v5(raw_text)
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
    
    # Git operations (commented out for safety during dev, user can run manually or I can uncomment)
    # run_command("git add .")
    # run_command('git commit -m "Update parsing V5"', cwd=os.getcwd())
    # run_command("git push origin main", cwd=os.getcwd())

if __name__ == "__main__":
    main()
