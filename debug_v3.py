
import os
import re
from pypdf import PdfReader

# Debug Chapter 1 specifically
pdf_path = "pdfs/1章.pdf"

if os.path.exists(pdf_path):
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
        
    lines = text.split('\n')
    
    # REPLICATE CLASSIFY LOGIC
    for i, line in enumerate(lines[:100]):
        kind = "UNKNOWN"
        data = None
        line = line.strip()
        
        if not line: kind="EMPTY"
        elif re.match(r'^Tip', line): kind="GARBAGE"
        elif re.match(r'^F\s*\d+', line): kind="GARBAGE"
        elif re.match(r'^(\d+(?:-\d+)?)$', line): kind="ID_ONLY"; data=line
        elif re.match(r'^(\d+(?:-\d+)?)\s+([^a-zA-Z].*)$', line): kind="ID_JP"; data=line
        elif re.match(r'^(\d+(?:-\d+)?)\s+([a-zA-Z].*)$', line): kind="ID_EN"; data=line
        elif '(' in line and ')' in line: kind="Q_LINE"
        
        print(f"{i:03d} [{kind}] {line}")
