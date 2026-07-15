import zipfile, re, os

docx = r'C:\Users\13522\Downloads\鹿小仓·店参谋 产品优化、分角色界面研判、落地执行最终阶段性方案.docx'
outp = r'C:\Users\13522\diancanmou\docs\product_review.txt'

with zipfile.ZipFile(docx) as z:
    xml = z.read('word/document.xml').decode('utf-8')

# Strip XML tags, preserve paragraph breaks
text = xml.replace('</w:p>', '\n').replace('<w:br/>', '\n').replace('</w:tr>', '\n')
text = re.sub(r'<[^>]+>', '', text)
text = re.sub(r'\n{3,}', '\n\n', text)
text = re.sub(r'  +', ' ', text)
text = text.strip()

os.makedirs(os.path.dirname(outp), exist_ok=True)
with open(outp, 'w', encoding='utf-8') as f:
    f.write(text)

print(f'Extracted {len(text)} chars to {outp}')
