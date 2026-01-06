
import os
from pypdf import PdfReader
import re

target_chapters = ["pdfs/1章.pdf", "pdfs/10章.pdf", "pdfs/24章.pdf"]

def analyze(path):
    print(f"\n{'='*20}\nAnalyzing {path}\n{'='*20}")
    if not os.path.exists(path):
        print("Not found")
        return

    try:
        reader = PdfReader(path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        
        lines = text.split('\n')
        # Print first 200 lines with line numbers for inspection
        for i, line in enumerate(lines[:200]):
            print(f"{i:03d}: {line.strip()}")
            
        print("\n... (truncated) ...")
    except Exception as e:
        print(e)

for p in target_chapters:
    analyze(p)
