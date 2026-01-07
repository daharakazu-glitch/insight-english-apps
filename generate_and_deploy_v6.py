
import docx
from docx.shared import RGBColor
import os
import re
import json
import unicodedata
from pathlib import Path

# Configuration
WORD_DIR = Path("word_files")
DOCS_DIR = Path("docs")
TEMPLATE_FILE = Path("template.html")

def setup_directories():
    if not DOCS_DIR.exists():
        DOCS_DIR.mkdir()

def get_chapter_number(filename):
    normalized = unicodedata.normalize('NFKC', filename)
    match = re.search(r'(\d+)', normalized)
    if match: return int(match.group(1))
    return 999

def is_japanese(text):
    for char in text:
        try:
            name = unicodedata.name(char, "")
            if "HIRAGANA" in name or "KATAKANA" in name or "CJK" in name:
                return True
        except:
             pass
    return False

def clean_text(text):
    # Remove hidden zero markers often found in these docs (e.g. '0'(white) before '17')
    # Actually, if we just strip standard whitespace, is it enough?
    # We might want to remove weird control characters.
    return text.strip()

def extract_items_from_docx(docx_path):
    doc = docx.Document(docx_path)
    
    # Storage
    # blocks = { "id": [ { "text": "...", "runs": [...] } ] }
    blocks = {}
    current_id = None
    
    # Regex for ID: '1', '1-1', '017', '17'
    # Valid IDs usually don't have text on the same line in this format?
    # Based on dump: "017   駅に着いた..." (Japanese on same line)
    # "018   It had been..." (English on same line)
    # So ID is a prefix.
    
    id_pattern = re.compile(r'^0?(\d+(?:-\d+)?)')
    
    all_paras = doc.paragraphs
    
    for p in all_paras:
        text = p.text.strip()
        if not text: continue
        
        # Check for ID match
        # Note: Sometimes there's a white '0' prefix uncaptured by .text if it's separate?
        # No, .text includes all.
        match = id_pattern.match(text)
        
        # Filter false positives: Page numbers, dates?
        # ID is usually followed by space.
        
        # Specialized filter for "File X" headers
        if text.startswith("File ") or text.startswith("Grasp ") or text.startswith("Words to Use"):
            continue
            
        if match:
             # Found a line starting with ID
             # Use the normalized ID (remove leading zero if regex caught it, but group 1 is the main part)
             # Wait, regex `^0?(\d...)` grabs the number.
             raw_id = match.group(1)
             
             # Heuristic: IDs are short. content follows.
             current_id = raw_id
             
             if current_id not in blocks:
                 blocks[current_id] = []
        
        # Append paragraph info to current ID
        if current_id:
            blocks[current_id].append(p)
    
    # Now process each block
    items = []
    
    # Sort IDs
    def sort_key(s):
        parts = s.split('-')
        try: return [int(p) for p in parts]
        except: return [9999]
    
    sorted_ids = sorted(blocks.keys(), key=sort_key)
    
    for bid in sorted_ids:
        paras = blocks[bid]
        
        # Components
        ja_lines = []
        q_lines = []
        ans_sentence_parts = [] # Will build the English sentence with {}
        ans_raw_words = [] # Plain list of answers
        expl_lines = []
        
        for p in paras:
            text = p.text.strip()
            if not text: continue
            
            # Remove ID
            clean_line = re.sub(r'^0?'+re.escape(bid)+r'\s*', '', text).strip()
            # Remove checkboxes
            clean_line = re.sub(r'[□]+', '', clean_line).strip()
            
            # Classification
            if "▶" in clean_line or clean_line.startswith("Tip"):
                expl_lines.append(clean_line)
                continue
            
            if is_japanese(clean_line):
                # Filter specific keywords
                if "基本" in clean_line: continue
                if "発展" in clean_line: continue
                if clean_line.startswith("○"): continue # Vocab notes
                
                # Check for "Words to Use" context?
                if "Words to Use" in clean_line: continue
                
                ja_lines.append(clean_line)
                continue
            
            # English Processing
            # 1. Filter "F 000" refs (often at start or end)
            # e.g. "F 023  it is raining" -> "it is raining"
            clean_line = re.sub(r'F\s*\d+\s*', '', clean_line).strip()
            
            has_valid_color = False
            colored_segments = []
            reconstructed_sent = ""
            
            for run in p.runs:
                r_text = run.text
                if not r_text: continue
                
                # Filter F-codes from run text too if possible? 
                # Doing it on reconstructed string is safer for structure.
                
                is_colored = False
                if run.font.color and run.font.color.rgb:
                    if run.font.color.rgb != RGBColor(255, 255, 255) and run.font.color.rgb != RGBColor(0, 0, 0):
                        if not re.match(r'^[ \t\n➡・]+$', r_text):
                             is_colored = True
                        
                if is_colored:
                    has_valid_color = True
                    reconstructed_sent += f"{{{r_text}}}"
                    colored_segments.append(r_text.strip())
                else:
                    reconstructed_sent += r_text
            
            # Clean reconstructed (ID, checkboxes, F-codes)
            reconstructed_sent = re.sub(r'^0?'+re.escape(bid)+r'\s*', '', reconstructed_sent).strip()
            reconstructed_sent = re.sub(r'[□]+', '', reconstructed_sent).strip()
            reconstructed_sent = re.sub(r'F\s*\d+\s*', '', reconstructed_sent).strip()
            
            # Decision
            has_blanks = "(" in clean_line or "（" in clean_line or "_" in clean_line
            
            if has_blanks:
                q_lines.append(clean_line)
            elif has_valid_color:
                ans_sentence_parts.append(reconstructed_sent)
                ans_raw_words.extend(colored_segments)
            else:
                if not ans_sentence_parts:
                     q_lines.append(clean_line)
                else:
                     expl_lines.append(clean_line)

        # Assemble
        ja_text = " ".join(ja_lines).strip()
        
        # Post-process Japanese: Keep only first sentence?
        # If it contains '。', keep up to the first '。'.
        if "。" in ja_text:
            parts = ja_text.split("。")
            ja_text = parts[0] + "。"
            # If the remainder had useful info? Usually it's hints.
        
        # Remove any remaining "○" or bracketed hints if they were inline?
        # e.g. "Translation (Hint)" -> "Translation"
        # Be careful not to remove grammar brackets or parens in math? (English app, so ok).
        
        q_text = " ".join(q_lines)
        en_text_with_brackets = " ".join(ans_sentence_parts) if ans_sentence_parts else "???"
        
        # Cleanup brackets
        en_text_with_brackets = re.sub(r'\{\s*\}', '', en_text_with_brackets)
        # Cleanup double spaces
        en_text_with_brackets = re.sub(r'\s+', ' ', en_text_with_brackets).strip()
        
        answer_text = ", ".join([w for w in ans_raw_words if w])
        
        items.append({
            "id": bid,
            "ja": ja_text,
            "en": en_text_with_brackets,
            "answer": answer_text,
            "explanation": "\n".join(expl_lines),
            "question": q_text
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

def main():
    print("--- Insight App Generator V6 (Word/Color Matching) ---")
    setup_directories()
    
    # Get all docx files
    files = list(WORD_DIR.glob("*.docx"))
    files.sort(key=lambda x: get_chapter_number(x.name))
    
    generated_links = []
    
    for docx_file in files:
        print(f"Processing {docx_file.name}...")
        try:
            items = extract_items_from_docx(docx_file)
            print(f"Extracted {len(items)} items.")
            
            chap_num = get_chapter_number(docx_file.name)
            html_content = generate_app(chap_num, items)
            
            output_name = f"chapter-{chap_num:02d}.html"
            output_path = DOCS_DIR / output_name
            
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            generated_links.append((output_name, f"Chapter {chap_num}"))
        except Exception as e:
            print(f"FAILED to process {docx_file.name}: {e}")
            import traceback
            traceback.print_exc()

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
    # run_command("git add .")
    # run_command('git commit -m "Update parsing V6 (Word)"', cwd=os.getcwd())
    # run_command("git push origin main", cwd=os.getcwd())

if __name__ == "__main__":
    main()
