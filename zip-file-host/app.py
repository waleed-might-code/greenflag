import os
import uuid
from flask import Flask, render_template, request, send_file, jsonify, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'Only .zip files are allowed'}), 400
    
    # Generate unique ID for the file
    file_id = str(uuid.uuid4())
    filename = f"{file_id}.zip"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    # Save the file
    file.save(filepath)
    
    # Generate download URL
    download_url = url_for('download_file', file_id=file_id, _external=True)
    
    return jsonify({
        'success': True,
        'file_id': file_id,
        'download_url': download_url,
        'original_filename': secure_filename(file.filename)
    })

@app.route('/download/<file_id>')
def download_file(file_id):
    filename = f"{file_id}.zip"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if not os.path.exists(filepath):
        return "File not found", 404
    
    return send_file(filepath, as_attachment=True, download_name='download.zip')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5027))
    app.run(host='0.0.0.0', port=port, debug=True)
