
from pypdf import PdfReader
from pathlib import Path

# Analyze the first PDF to understand structure
pdf_path = list(Path("pdfs").glob("*.pdf"))[0]
print(f"Analyzing: {pdf_path.name}")

reader = PdfReader(pdf_path)
text = reader.pages[0].extract_text()
print("--- START TEXT ---")
print(text)
print("--- END TEXT ---")
