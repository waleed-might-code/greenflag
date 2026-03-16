import os
import re
import json
import zipfile
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['RESULTS_FOLDER'] = 'results'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

def parse_whatsapp_chat(text_content):
    """Parse WhatsApp chat export format"""
    # Replace Unicode characters that WhatsApp uses
    text_content = text_content.replace('\u202f', ' ')  # NARROW NO-BREAK SPACE
    text_content = text_content.replace('\u200e', '')   # LEFT-TO-RIGHT MARK
    text_content = text_content.replace('\u200f', '')   # RIGHT-TO-LEFT MARK
    text_content = text_content.replace('\u200b', '')   # ZERO-WIDTH SPACE
    
    message_pattern = r'^\[(\d{1,2}/\d{1,2}/\d{2}), (\d{1,2}:\d{2}(?::\d{2})? [AP]M)\] ([^:]+): (.+)$'
    messages = []
    current_message = None
    
    for line in text_content.split('\n'):
        line = line.strip()
        
        if not line:
            continue
            
        match = re.match(message_pattern, line)
        if match:
            if current_message:
                messages.append(current_message)
            date, time, sender, content = match.groups()
            current_message = {
                'date': date,
                'time': time,
                'sender': sender.strip(),
                'content': content.strip()
            }
        elif current_message:
            current_message['content'] += ' ' + line
    
    if current_message:
        messages.append(current_message)
    
    return messages

def analyze_with_groq(messages):
    """Analyze chat messages using Groq AI"""
    sample_size = min(len(messages), 200)
    sample_messages = messages[:sample_size]
    
    chat_text = '\n'.join([
        f"{msg['sender']}: {msg['content']}" 
        for msg in sample_messages
    ])
    
    prompt = f"""Analyze this WhatsApp conversation and provide a relationship health assessment.

Chat excerpt ({sample_size} messages):
{chat_text}

Provide your analysis in the following JSON format:
{{
    "overall_verdict": "healthy" or "concerning" or "toxic",
    "health_score": 0-100,
    "green_flags": [
        {{"title": "Flag name", "description": "Detailed explanation", "examples": ["quote1", "quote2"]}}
    ],
    "red_flags": [
        {{"title": "Flag name", "description": "Detailed explanation", "examples": ["quote1", "quote2"]}}
    ],
    "summary": "Overall relationship assessment",
    "recommendations": ["advice1", "advice2", "advice3"]
}}

Focus on communication patterns, respect, boundaries, emotional support, and conflict resolution."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a relationship counselor analyzing chat conversations. Provide honest, helpful assessments in valid JSON format."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        
        result_text = response.choices[0].message.content.strip()
        
        if result_text.startswith('```json'):
            result_text = result_text[7:]
        if result_text.startswith('```'):
            result_text = result_text[3:]
        if result_text.endswith('```'):
            result_text = result_text[:-3]
        result_text = result_text.strip()
        
        analysis = json.loads(result_text)
        return analysis
        
    except json.JSONDecodeError as e:
        return {
            "overall_verdict": "error",
            "health_score": 0,
            "green_flags": [],
            "red_flags": [],
            "summary": f"Failed to parse AI response: {str(e)}",
            "recommendations": ["Please try again with a different chat export"]
        }
    except Exception as e:
        return {
            "overall_verdict": "error",
            "health_score": 0,
            "green_flags": [],
            "red_flags": [],
            "summary": f"Analysis error: {str(e)}",
            "recommendations": ["Please try again"]
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.zip'):
        return jsonify({'success': False, 'error': 'Please upload a .zip file'}), 400
    
    try:
        zip_filename = f"{uuid.uuid4()}.zip"
        zip_path = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)
        file.save(zip_path)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            txt_files = [f for f in zip_ref.namelist() if f.endswith('.txt')]
            
            if not txt_files:
                os.remove(zip_path)
                return jsonify({'success': False, 'error': 'No .txt file found in the zip'}), 400
            
            with zip_ref.open(txt_files[0]) as txt_file:
                text_content = txt_file.read().decode('utf-8', errors='ignore')
        
        messages = parse_whatsapp_chat(text_content)
        
        if len(messages) < 10:
            os.remove(zip_path)
            return jsonify({'success': False, 'error': 'Not enough messages to analyze (minimum 10 required)'}), 400
        
        ai_analysis = analyze_with_groq(messages)
        
        analysis = {
            **ai_analysis,
            'message_count': len(messages),
            'analyzed_at': datetime.now().isoformat(),
            'participants': list(set(msg['sender'] for msg in messages[:100]))[:2]
        }
        
        result_id = str(uuid.uuid4())[:8]
        result_path = os.path.join(app.config['RESULTS_FOLDER'], f'{result_id}.json')
        with open(result_path, 'w') as f:
            json.dump(analysis, f)
        
        os.remove(zip_path)
        
        return jsonify({
            'success': True,
            'share_url': f'/result/{result_id}',
            'result_id': result_id
        })
    
    except Exception as e:
        if 'zip_path' in locals() and os.path.exists(zip_path):
            os.remove(zip_path)
        return jsonify({'success': False, 'error': f'Analysis failed: {str(e)}'}), 500

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/result/<result_id>')
def result(result_id):
    result_path = os.path.join(app.config['RESULTS_FOLDER'], f'{result_id}.json')
    if not os.path.exists(result_path):
        return "Result not found", 404
    
    with open(result_path, 'r') as f:
        analysis = json.load(f)
    
    return render_template('result.html', analysis=analysis, result_id=result_id)

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'service': 'Green Flag Checker'})

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5030)))
