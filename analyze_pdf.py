
import os
from pypdf import PdfReader

pdf_path = "pdfs/1章.pdf"

if not os.path.exists(pdf_path):
    print(f"Error: {pdf_path} not found.")
else:
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        print(f"--- Extracted Text from {pdf_path} ---")
        print(text[:3000]) # Print first 3000 chars to see enough context
        print("\n--- End of Text ---")
    except Exception as e:
        print(f"Error: {e}")
