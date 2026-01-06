
import os
import re
import sys
import shutil
import subprocess
import unicodedata
from pathlib import Path
from pypdf import PdfReader

# Configuration
PDF_DIR = Path("pdfs")
DOCS_DIR = Path("docs")
TEMPLATE_FILE = Path("template.html")
GITHUB_PAGES_BRANCH = "main" # or master, depending on repo

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
    """Create necessary directories."""
    if not DOCS_DIR.exists():
        DOCS_DIR.mkdir()
        print(f"Created {DOCS_DIR}")
    else:
        print(f"{DOCS_DIR} already exists.")

    if not PDF_DIR.exists():
        print(f"Warning: {PDF_DIR} does not exist. Please place PDFs in this folder.")
        PDF_DIR.mkdir()
    
    if not TEMPLATE_FILE.exists():
         print(f"Warning: {TEMPLATE_FILE} not found. Please provide a template.")
         # Create a dummy template if missing to allow logic to proceed (or fail gracefully later)
         with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
             f.write("<html><body><h1>App from {{ title }}</h1><div id='content'>{{ content }}</div></body></html>")
         print("Created dummy template.html")

def extract_text_from_pdf(pdf_path):
    """Extract text from a single PDF using pypdf."""
    try:
        reader = PdfReader(pdf_path)
        text_content = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_content.append(text)
        return "\n".join(text_content)
    except Exception as e:
        print(f"Failed to read {pdf_path}: {e}")
        return ""

def parse_pdf_content(text):
    """
    Parse raw PDF text into structured data.
    This is a heuristic approach. Adjust regex based on actual PDF format.
    """
    return {
        "content": text.replace("\n", "<br>")
    }

def generate_html(data, chapter_title):
    """Generate HTML content by filling the template."""
    try:
        with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
            template = f.read()
        
        html = template.replace("{{ content }}", data.get("content", ""))
        html = html.replace("{{ title }}", chapter_title)
        
        for key, value in data.items():
            html = html.replace(f"{{{{ {key} }}}}", str(value))
            
        return html
    except Exception as e:
        print(f"Error generating HTML: {e}")
        return "<html><body>Error generating content</body></html>"

def get_github_pages_url():
    """Calculate the GitHub Pages URL from the remote 'origin'."""
    url = run_command("git remote get-url origin")
    if not url:
        return None
    
    match = re.search(r"[:/]([\w-]+)/([\w.-]+?)(\.git)?$", url)
    if match:
        user = match.group(1)
        repo = match.group(2)
        return f"https://{user}.github.io/{repo}/"
    return None

def get_chapter_number(filename):
    """Extract chapter number from filename, handling wide chars."""
    # Normalize to NFKC to convert full-width numbers to ascii
    normalized = unicodedata.normalize('NFKC', filename)
    match = re.search(r'(\d+)', normalized)
    if match:
        return int(match.group(1))
    return 99999 # Sort to end if no number found

def main():
    print("--- Starting Auto-Deployment Script ---")
    
    # 1. Setup
    setup_directories()
    
    # 2. Process PDFs
    generated_files = []
    # Sort files naturally (1, 2, ... 10) instead of ASCII (1, 10, 2...)
    pdf_files = list(PDF_DIR.glob("*.pdf"))
    pdf_files.sort(key=lambda x: get_chapter_number(x.name))
    
    if not pdf_files:
        print("No PDF files found in pdfs/ folder.")
    
    for pdf_file in pdf_files:
        print(f"Processing {pdf_file.name}...")
        raw_text = extract_text_from_pdf(pdf_file)
        data = parse_pdf_content(raw_text)
        
        # Use the number from filename if possible, otherwise list index
        chapter_id = get_chapter_number(pdf_file.name)
        if chapter_id == 99999:
             # Fallback if no number in filename (shouldn't happen with current files)
             chapter_id = len(generated_files) + 1
             
        
        output_filename = f"chapter-{chapter_id:02d}.html"
        output_path = DOCS_DIR / output_filename
        
        chapter_title = f"Chapter {chapter_id}"
        
        html_content = generate_html(data, chapter_title)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        generated_files.append((output_filename, chapter_title))
        print(f"Saved {output_filename}")

    # 3. Create Index Page
    print("Creating index.html...")
    index_content = "<html><head><title>English Apps Index</title></head><body>"
    index_content += "<h1>English Learning Apps</h1><ul>"
    for fname, title in generated_files:
        index_content += f'<li><a href="{fname}">{title}</a></li>'
    index_content += "</ul></body></html>"
    
    with open(DOCS_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(index_content)
    
    # 4. Git Deployment
    print("Committing and pushing to Git...")
    run_command("git add .")
    run_command('git commit -m "Auto-generated apps from latest PDFs"')
    run_command(f"git push origin {GITHUB_PAGES_BRANCH}")
    
    # 5. Output URLs
    base_url = get_github_pages_url()
    if base_url:
        print("\n**以下のURLで公開されます：**")
        print(f"Index: {base_url}")
        for fname, title in generated_files:
            print(f"- {title}: {base_url}{fname}")
    else:
        print("Could not determine GitHub Pages URL.")

if __name__ == "__main__":
    main()
