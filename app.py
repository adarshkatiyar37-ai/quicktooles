import os
import fitz  # PyMuPDF
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
THUMBNAIL_FOLDER = 'static/thumbnails'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

CURRENT_PDF = os.path.join(UPLOAD_FOLDER, "input.pdf")
PROCESSED_PDF = os.path.join(UPLOAD_FOLDER, "processed.pdf")

def generate_thumbnails(pdf_path):
    for f in os.listdir(THUMBNAIL_FOLDER):
        if f.endswith('.png'):
            try: os.remove(os.path.join(THUMBNAIL_FOLDER, f))
            except Exception: pass
            
    doc = fitz.open(pdf_path)
    page_data = []
    
    max_pages = min(len(doc), 40) 
    for page_num in range(max_pages):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(0.1, 0.1))
        image_name = f"page_{page_num}.png"
        pix.save(os.path.join(THUMBNAIL_FOLDER, image_name))
        
        page_data.append({
            'index': page_num,
            'display_num': page_num + 1,
            'image': image_name,
            'rotation': page.rotation
        })
    doc.close()
    return page_data

def is_semi_blank(page):
    text = page.get_text().strip()
    if len(text) > 3:  
        return False
        
    page_rect = page.rect
    total_area = page_rect.width * page_rect.height
    
    drawings = page.get_drawings()
    marked_area = 0
    
    for draw in drawings:
        rect = draw.get("rect", fitz.Rect(0, 0, 0, 0))
        marked_area += rect.width * rect.height
        
    if total_area > 0 and (marked_area / total_area) < 0.015:
        if len(page.get_images()) == 0:
            return True
            
    return False

def run_auto_clean(input_path, output_path):
    doc = fitz.open(input_path)
    new_doc = fitz.open()
    deleted_blanks = 0
    rotated_count = 0
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        
        if is_semi_blank(page):
            deleted_blanks += 1
            continue
            
        # 🛠️ MULTI-DIRECTIONAL TEXT & LAYOUT ROTATION ENGINE
        try:
            # Step 1: Attempt Text Flow Analytics (OSD)
            osd = page.get_text("osd")
            rotation_needed = osd.get("rotate", 0)
            confidence = osd.get("confidence", 0.0)
            
            # Agar text oriented hai aur algorithm secure hai, toh shift karein
            if rotation_needed in [90, 180, 270] and confidence > 3.5:
                new_rot = (page.rotation + rotation_needed) % 360
                page.set_rotation(new_rot)
                rotated_count += 1
            else:
                # Step 2: Fallback Layout Engine (If OCR confidence is low due to poor scan quality)
                rect = page.rect
                # Agar width, height se badi hai (Page landscape mode me leeta hua hai)
                if rect.width > rect.height:
                    # Is government file ke standards ke mutabik 270 ya 90 degree set karein vertical alignment ke liye
                    page.set_rotation(270)
                    rotated_count += 1
        except Exception:
            # Step 3: Hard Fallback for structural safety
            rect = page.rect
            if rect.width > rect.height:
                page.set_rotation(270)
                rotated_count += 1
            
        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        
    if len(new_doc) == 0 and len(doc) > 0:
        new_doc.insert_pdf(doc, from_page=0, to_page=0)

    # Deflate compresses the binary stream to prevent zero-byte corrupt downloads
    new_doc.save(output_path, garbage=3, deflate=True)
    new_doc.close()
    doc.close()
    return deleted_blanks, rotated_count

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'pdf_file' not in request.files: return redirect(request.url)
        file = request.files['pdf_file']
        if file.filename == '': return redirect(request.url)
        
        mode = request.form.get('mode') 
        
        if file and file.filename.endswith('.pdf'):
            file.save(CURRENT_PDF)
            
            if mode == 'auto':
                blanks, rotated = run_auto_clean(CURRENT_PDF, PROCESSED_PDF)
                return render_template('index.html', download=True, blanks=blanks, rotated=rotated)
            
            elif mode == 'manual':
                doc = fitz.open(CURRENT_PDF)
                if os.path.exists(PROCESSED_PDF): os.remove(PROCESSED_PDF)
                doc.save(PROCESSED_PDF)
                doc.close()
                return redirect(url_for('manual_editor'))
                
    return render_template('index.html', download=False)

@app.route('/editor')
def manual_editor():
    pages = generate_thumbnails(PROCESSED_PDF)
    return render_template('editor.html', pages=pages)

@app.route('/delete_page', methods=['POST'])
def delete_page():
    data = request.json
    page_idx = int(data['index'])
    doc = fitz.open(PROCESSED_PDF)
    temp_path = os.path.join(UPLOAD_FOLDER, "temp_processed.pdf")
    new_doc = fitz.open()
    for i in range(len(doc)):
        if i != page_idx: new_doc.insert_pdf(doc, from_page=i, to_page=i)
    new_doc.save(temp_path, garbage=3, deflate=True)
    new_doc.close()
    doc.close()
    if os.path.exists(PROCESSED_PDF): os.remove(PROCESSED_PDF)
    os.rename(temp_path, PROCESSED_PDF)
    return jsonify({'status': 'success'})

@app.route('/rotate_page', methods=['POST'])
def rotate_page():
    data = request.json
    page_idx = int(data['index'])
    doc = fitz.open(PROCESSED_PDF)
    temp_path = os.path.join(UPLOAD_FOLDER, "temp_processed.pdf")
    page = doc[page_idx]
    page.set_rotation((page.rotation + 90) % 360)
    doc.save(temp_path, garbage=3, deflate=True)
    doc.close()
    if os.path.exists(PROCESSED_PDF): os.remove(PROCESSED_PDF)
    os.rename(temp_path, PROCESSED_PDF)
    return jsonify({'status': 'success'})

@app.route('/download')
def download():
    return send_file(PROCESSED_PDF, as_attachment=True, download_name="Cleaned_Document.pdf")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
