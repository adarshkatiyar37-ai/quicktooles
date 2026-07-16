import os
import fitz  # PyMuPDF
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
THUMBNAIL_FOLDER = 'static/thumbnails'

# Folders banana ensure karein
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

CURRENT_PDF = os.path.join(UPLOAD_FOLDER, "input.pdf")
PROCESSED_PDF = os.path.join(UPLOAD_FOLDER, "processed.pdf")

def generate_thumbnails(pdf_path):
    # Purane thumbnails saaf karein taaki nayi file ke hi dikhein
    for f in os.listdir(THUMBNAIL_FOLDER):
        if f.endswith('.png'):
            try:
                os.remove(os.path.join(THUMBNAIL_FOLDER, f))
            except Exception:
                pass
            
    doc = fitz.open(pdf_path)
    page_data = []
    
    # 800 pages ke liye initial workspace me safety ke liye pehle 100 pages load karte hain
    max_pages = min(len(doc), 100) 
    for page_num in range(max_pages):
        page = doc[page_num]
        # Low resolution tak ki loading super-fast ho
        pix = page.get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
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

def run_auto_clean(input_path, output_path):
    doc = fitz.open(input_path)
    new_doc = fitz.open()
    deleted_blanks = 0
    rotated_count = 0
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        has_text = page.get_text().strip()
        has_images = len(page.get_images()) > 0
        
        # 1. Blank page delete logic
        if not has_text and not has_images:
            deleted_blanks += 1
            continue
            
        # 2. Auto rotation logic
        try:
            osd = page.get_text("osd")
            rotation_needed = osd.get("rotate", 0)
        except Exception:
            rotation_needed = page.rotation
            
        if rotation_needed != 0:
            new_rot = (page.rotation - rotation_needed) % 360
            page.set_rotation(new_rot)
            rotated_count += 1
            
        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        
    new_doc.save(output_path)
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
                # OPTION 1: Poora Kaam Automatic
                blanks, rotated = run_auto_clean(CURRENT_PDF, PROCESSED_PDF)
                return render_template('index.html', download=True, blanks=blanks, rotated=rotated)
            
            elif mode == 'manual':
                # OPTION 2: Poora Kaam Manually
                doc = fitz.open(CURRENT_PDF)
                if os.path.exists(PROCESSED_PDF):
                    os.remove(PROCESSED_PDF)
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
    
    # Naye document me delete kiye gaye page ke alawa baaki sab daalna
    new_doc = fitz.open()
    for i in range(len(doc)):
        if i != page_idx:
            new_doc.insert_pdf(doc, from_page=i, to_page=i)
            
    new_doc.save(temp_path)
    new_doc.close()
    doc.close()
    
    # Mac/Windows file replace permission fix
    if os.path.exists(PROCESSED_PDF):
        os.remove(PROCESSED_PDF)
    os.rename(temp_path, PROCESSED_PDF)
    
    return jsonify({'status': 'success'})

@app.route('/rotate_page', methods=['POST'])
def rotate_page():
    data = request.json
    page_idx = int(data['index'])
    
    doc = fitz.open(PROCESSED_PDF)
    temp_path = os.path.join(UPLOAD_FOLDER, "temp_processed.pdf")
    
    # Page ko 90 degree clockwise ghumana
    page = doc[page_idx]
    page.set_rotation((page.rotation + 90) % 360)
    
    doc.save(temp_path)
    doc.close()
    
    if os.path.exists(PROCESSED_PDF):
        os.remove(PROCESSED_PDF)
    os.rename(temp_path, PROCESSED_PDF)
    
    return jsonify({'status': 'success'})

@app.route('/download')
def download():
    return send_file(PROCESSED_PDF, as_attachment=True, download_name="Final_Document.pdf")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)