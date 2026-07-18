import os
import fitz  # PyMuPDF
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify
from google.cloud import vision

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
THUMBNAIL_FOLDER = 'static/thumbnails'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

CURRENT_PDF = os.path.join(UPLOAD_FOLDER, "input.pdf")
PROCESSED_PDF = os.path.join(UPLOAD_FOLDER, "processed.pdf")

# Google Cloud Vision key initialization check
KEY_PATH = "service_account.json"
if os.path.exists(KEY_PATH):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_PATH
else:
    print("WARNING: service_account.json missing. Running in basic layout fallback mode.")

def analyze_handwritten_page(image_bytes):
    if not os.path.exists(KEY_PATH):
        return "", None
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)
        response = client.document_text_detection(image=image)
        full_text = response.full_text_annotation.text.strip()
        return full_text, response
    except Exception as e:
        print(f"AI Connection Error: {e}")
        return "", None

def generate_thumbnails(pdf_path):
    for f in os.listdir(THUMBNAIL_FOLDER):
        if f.endswith('.png'):
            try: os.remove(os.path.join(THUMBNAIL_FOLDER, f))
            except Exception: pass
            
    try:
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
    except Exception as e:
        print(f"Thumbnail generation error: {e}")
        return []

def run_pure_ai_cleaner(input_path, output_path):
    doc = fitz.open(input_path)
    new_doc = fitz.open()
    deleted_blanks = 0
    rotated_count = 0
    total_pages = len(doc)
    
    # ⚡ CRASH FIX: Is loop mechanism se page deletion par array index mismatch nahi hoga
    for page_num in range(total_pages):
        page = doc[page_num]
        
        # High resolution render for OCR stability
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        image_bytes = pix.tobytes("png")
        
        text_content, ai_response = analyze_handwritten_page(image_bytes)
        clean_text = "".join([c for c in text_content if c.isalnum()])
        
        # 🛑 FINAL BLANK DETECTION (Keeps ink marks safe only if meaningful text exists)
        if os.path.exists(KEY_PATH) and len(clean_text) < 3:
            deleted_blanks += 1
            continue  
        elif not os.path.exists(KEY_PATH):
            # Layout metrics algorithm fallback if key is not active
            if len(page.get_text().strip()) == 0 and len(page.get_drawings()) == 0 and len(page.get_images()) == 0:
                deleted_blanks += 1
                continue
            
        # 🔄 FINAL ORIENTATION ENGINE
        rotation_angle = 0
        rotation_forced = False
        
        if ai_response and ai_response.full_text_annotation.pages:
            vision_page = ai_response.full_text_annotation.pages[0]
            for block in vision_page.blocks:
                vertices = block.bounding_box.vertices
                if len(vertices) == 4:
                    width_step = abs(vertices[1].x - vertices[0].x)
                    height_step = abs(vertices[2].y - vertices[1].y)
                    
                    if height_step > width_step and page.rect.width > page.rect.height:
                        rotation_angle = 270
                        rotation_forced = True
                        break
                        
        if not rotation_forced and page.rect.width > page.rect.height:
            rotation_angle = 270
            
        # Isolated compilation window to prevent binary object stream breakdown
        temp_doc = fitz.open()
        temp_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        
        if rotation_angle != 0:
            temp_doc[0].set_rotation(rotation_angle)
            rotated_count += 1
            
        new_doc.insert_pdf(temp_doc, from_page=0, to_page=0)
        temp_doc.close()
        
    if len(new_doc) == 0 and len(doc) > 0:
        new_doc.insert_pdf(doc, from_page=0, to_page=0)

    if os.path.exists(output_path):
        try: os.remove(output_path)
        except Exception: pass
        
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
            if os.path.exists(CURRENT_PDF):
                try: os.remove(CURRENT_PDF)
                except Exception: pass
            file.save(CURRENT_PDF)
            
            if mode == 'auto':
                blanks, rotated = run_pure_ai_cleaner(CURRENT_PDF, PROCESSED_PDF)
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
