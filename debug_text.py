
from pypdf import PdfReader
reader = PdfReader("pdfs/1章.pdf")
text = ""
for page in reader.pages:
    text += page.extract_text() + "\n"
print(text[:2000])
