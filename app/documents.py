import base64
import html
import io
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import fitz
from lxml import etree
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "m": "http://schemas.openxmlformats.org/officeDocument/2006/math", "a": "http://schemas.openxmlformats.org/drawingml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
MAX_PAGES = 20


def local(element):
    return etree.QName(element).localname


def mathml(node):
    tag = local(node)
    children = list(node)
    def child(name):
        found = node.find(f"m:{name}", NS)
        return mathml(found) if found is not None else "<mrow></mrow>"
    if tag.endswith("Pr"):
        return ""
    if tag == "t":
        return "<mtext>" + html.escape(node.text or "") + "</mtext>"
    if tag == "f":
        return f"<mfrac>{child('num')}{child('den')}</mfrac>"
    if tag == "sSup":
        return f"<msup>{child('e')}{child('sup')}</msup>"
    if tag == "sSub":
        return f"<msub>{child('e')}{child('sub')}</msub>"
    if tag == "sSubSup":
        return f"<msubsup>{child('e')}{child('sub')}{child('sup')}</msubsup>"
    if tag == "rad":
        deg = node.find("m:deg", NS)
        if deg is not None and ''.join(deg.itertext()).strip():
            return f"<mroot>{child('e')}{child('deg')}</mroot>"
        return f"<msqrt>{child('e')}</msqrt>"
    if tag == "d":
        return f"<mrow><mo>(</mo>{child('e')}<mo>)</mo></mrow>"
    if tag == "nary":
        char = node.find("m:naryPr/m:chr", NS)
        symbol = char.get("{" + NS['m'] + "}val", "∑") if char is not None else "∑"
        return f"<mrow><munderover><mo>{html.escape(symbol)}</mo>{child('sub')}{child('sup')}</munderover>{child('e')}</mrow>"
    if tag in ("oMath", "oMathPara"):
        return '<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow>' + ''.join(mathml(c) for c in children) + '</mrow></math>' if tag == 'oMath' else ''.join(mathml(c) for c in children)
    return "<mrow>" + ''.join(mathml(c) for c in children) + "</mrow>"


def docx_html(file_path):
    with zipfile.ZipFile(file_path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 150 * 1024 * 1024:
            raise ValueError("DOCX解压体积过大，请拆分资料")
        xml = archive.read("word/document.xml")
        tree = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        rels = {}
        if "word/_rels/document.xml.rels" in archive.namelist():
            rel_tree = etree.fromstring(archive.read("word/_rels/document.xml.rels"), parser=etree.XMLParser(resolve_entities=False, no_network=True))
            for rel in rel_tree:
                if rel.get("TargetMode") != "External":
                    target = "word/" + rel.get("Target", "").lstrip("/")
                    rels[rel.get("Id")] = target
        def inline(node):
            name = local(node)
            if name == "t":
                return html.escape(node.text or "")
            if name in ('oMath', 'oMathPara'):
                return mathml(node)
            if name == "br":
                kind = node.get("{" + NS['w'] + "}type")
                return '<span class="page-break"></span>' if kind == "page" else "<br>"
            if name == "tab":
                return "&emsp;"
            if name in ('drawing', 'pict'):
                images = []
                for blip in node.findall('.//a:blip', NS):
                    rid = blip.get("{" + NS['r'] + "}embed")
                    target = rels.get(rid)
                    if target in archive.namelist():
                        data = archive.read(target)
                        try:
                            image = Image.open(io.BytesIO(data)).convert("RGB")
                            buff = io.BytesIO(); image.save(buff, "PNG")
                            images.append('<img src="data:image/png;base64,' + base64.b64encode(buff.getvalue()).decode() + '">')
                        except Exception:
                            images.append('<p>图片格式暂不支持，请核对原文件或转为PDF。</p>')
                return ''.join(images)
            if name.endswith('Pr') or name == 'sectPr':
                return ""
            return ''.join(inline(c) for c in node)
        output = []
        body = tree.find('w:body', NS)
        if body is None:
            raise ValueError("DOCX正文为空")
        for node in body:
            name = local(node)
            if name == 'p':
                output.append('<p>' + inline(node) + '</p>')
            elif name == 'tbl':
                output.append('<table>')
                for tr in node.findall('w:tr', NS):
                    output.append('<tr>' + ''.join('<td>' + inline(tc) + '</td>' for tc in tr.findall('w:tc', NS)) + '</tr>')
                output.append('</table>')
        return '<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><style>@page{size:A4;margin:20mm}body{font:16px/1.8 "Microsoft YaHei",sans-serif;color:#111;background:white}p{margin:10px 0;white-space:pre-wrap}img{max-width:100%;max-height:700px}table{width:100%;border-collapse:collapse}td{border:1px solid #aaa;padding:8px}math{font-size:20px}.page-break{display:block;break-before:page}</style><body>' + ''.join(output) + '</body></html>'


def preview_pdf(path, folder):
    result = []
    with fitz.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF受密码保护，请去除密码后重新上传")
        if not len(doc) or len(doc) > MAX_PAGES:
            raise ValueError("资料最多支持20页，请拆分后上传")
        for i, page in enumerate(doc):
            # Keep both dimensions bounded to prevent abnormal PDFs exhausting memory.
            scale = min(1.7, 1800 / max(page.rect.width, page.rect.height))
            preview = folder / f"page-{i+1}.jpg"
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pix.save(str(preview))
            result.append({"path": str(preview), "text": page.get_text()[:50000]})
    return result


def convert_file(path, kind, folder):
    folder.mkdir(parents=True, exist_ok=True)
    if kind == 'image':
        with Image.open(path) as original:
            if original.width * original.height > 40_000_000:
                raise ValueError("图片像素过大，请缩小到4000万像素以内")
            image = ImageOps.exif_transpose(original).convert('RGB')
            image.thumbnail((2200, 2200))
            output = folder / 'page-1.jpg'
            image.save(output, 'JPEG', quality=91)
        return [{"path": str(output), "text": ""}], ""
    if kind == 'pdf':
        return preview_pdf(path, folder), ""
    if kind == 'docx':
        try:
            converted = docx_html(path)
        except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError):
            raise ValueError("DOCX无效或无法读取，请另存为DOCX或PDF") from None
        html_path = folder / 'converted.html'
        html_path.write_text(converted, encoding='utf-8')
        pdf_path = folder / 'converted.pdf'
        node = os.environ.get('CUOTI_NODE', shutil.which('node') or '')
        if not node:
            raise ValueError("Word预览需要Node.js与浏览器，请按技术文档安装，或转为PDF")
        proc = subprocess.run([node, str(ROOT/'scripts'/'render-docx.cjs'), str(html_path), str(pdf_path)], capture_output=True, timeout=60)
        if proc.returncode:
            raise ValueError("Word预览转换失败，请检查浏览器依赖或另存为PDF")
        pages = preview_pdf(pdf_path, folder)
        return pages, "Word采用内容重排预览；常用公式、表格和图片保留，复杂排版请与原件核对，必要时另存为PDF。"
    raise ValueError("文件格式不支持")
