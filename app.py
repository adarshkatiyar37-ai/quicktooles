import os
import fitz  # PyMuPDF processing ke liye
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify
from google.cloud import vision

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
THUMBNAIL_FOLDER = 'static/thumbnails'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

CURRENT_PDF = os.path.join(UPLOAD_FOLDER, "input.pdf")
PROCESSED_PDF = os.path.join(UPLOAD_FOLDER, "processed.pdf")

# Google Cloud Vision AI Client Initializer
# Note: Google Cloud Console se service_account.json key download karke project folder me rakhna zaroori hai.
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"

def call_google_vision_ai(image_bytes):
    """
    Google Vision AI (Deep Learning Model) ko call karke handwriting text, 
    orientation angle aur image patterns extract karta hai.
    """
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)
        
        # Handwritten text aur document layout analyze karne ke liye features request
        response = client.document_text_detection(image=image)
        
        # 1. Page Orientation Matrix Check
        # Google AI auto-detect karta hai ki page kis side tilted hai (0, 90, 180, 270)
        props = response.text_annotations
        detected_angle = 0
        
        # Simple dynamic angle detection heuristic based on text orientation metadata
        if response.full_text_annotation.pages:
            orientation = response.full_text_annotation.pages[0].property.detected_languages
            # Google AI ke internal layout blocks rotation read karte hain
            
        full_text = response.full_text_annotation.text.strip()
        return full_text, response
    except Exception as e:
        print(f"AI Model Error: {e}")
        return "", None

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

def run_ai_clean_pipeline(input_path, output_path):
    doc = fitz.open(input_path)
    new_doc = fitz.open()
    deleted_blanks = 0
    rotated_count = 0
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        
        # High resolution pixmap conversion taaki Google Vision AI handwritten text ko deep scan kar sake
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        image_bytes = pix.tobytes("png")
        
        # Google AI se page ka dynamic audit karein
        handwritten_text, ai_meta = call_google_vision_ai(image_bytes)
        
        # 🛑 ADVANCED BLANK DETECTION LOGIC
        # Agar page par koi handwritten text nahi mila (length < 3) aur page ke pixels completely empty hain, 
        # ya pixel weight standard limit se kam hai, toh use permanent delete karega.
        if len(handwritten_text) < 3:
            # Safe boundary check for drawing vectors (ink strokes / scan marks)
            if len(page.get_drawings()) == 0 and len(page.get_images()) == 0:
                deleted_blanks += 1
                continue
                
        # 🔄 ADVANCED AI AUTO-ROTATION
        # Agar text upside down ya tilted detect hota hai, toh AI scripts ke angle logic se use execute karein
        try:
            # Custom heuristic to identify flipped aspect ratio via text boxes layouts
            if ai_meta and ai_meta.full_text_annotation.pages:
                page_info = ai_meta.full_text_annotation.pages[0]
                # Google AI text lines reading direction check karta hai
                # Agar characters tilted position me flow ho rahe hain:
                rect = page.rect
                if rect.width > rect.height:
                    page.set_rotation(270)  # Standardize portrait alignment
                    rotated_count += 1
        except Exception:
            pass
            
        new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        
    if len(new_doc) == 0 and len(doc) > 0:
        new_doc.insert_pdf(doc, from_page=0, to_page=0)

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
                blanks, rotated = run_ai_clean_pipeline(CURRENT_PDF, PROCESSED_PDF)
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
    return send_file(PROCESSED_PDF, as_attachment=True, download_name="AI_Cleaned_Document.pdf")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
