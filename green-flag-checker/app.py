import os
import json
import zipfile
import tempfile
from flask import Flask, render_template, request, jsonify
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def parse_whatsapp_chat(text):
    """Parse WhatsApp chat and extract key information"""
    lines = text.split('\n')
    messages = []
    for line in lines:
        if line.strip():
            messages.append(line)
    
    summary = f"Chat contains {len(messages)} messages.\n\n"
    summary += "Sample messages:\n"
    summary += '\n'.join(messages[:50])  # First 50 messages
    
    return summary

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        chat_text = ""
        
        # Handle zip files
        if file.filename.endswith('.zip'):
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = os.path.join(tmpdir, 'chat.zip')
                file.save(zip_path)
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    # Extract only .txt files
                    txt_files = [f for f in zip_ref.namelist() if f.endswith('.txt')]
                    if not txt_files:
                        return jsonify({'error': 'No .txt file found in zip'}), 400
                    
                    zip_ref.extract(txt_files[0], tmpdir)
                    with open(os.path.join(tmpdir, txt_files[0]), 'r', encoding='utf-8') as f:
                        chat_text = f.read()
        
        # Handle txt files
        elif file.filename.endswith('.txt'):
            chat_text = file.read().decode('utf-8')
        
        else:
            return jsonify({'error': 'Please upload a .txt or .zip file'}), 400
        
        if not chat_text:
            return jsonify({'error': 'Chat file is empty'}), 400
        
        # Parse and summarize chat
        chat_summary = parse_whatsapp_chat(chat_text)
        
        # Send to Groq for analysis
        prompt = f"""Analyze this WhatsApp chat and determine if it shows green flags or red flags in the relationship.

{chat_summary}

Provide your analysis in the following format:
1. VERDICT: Either "🟢 Green Flag" or "🔴 Red Flag"
2. SCORE: A number from 0-100
3. TOP REASONS: List 3-5 key reasons with specific message-based evidence
4. VIBE SUMMARY: A short 2-3 sentence summary of the overall vibe
5. CLOSING LINE: A funny, witty one-liner about this chat

Be specific, insightful, and a bit humorous."""

        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1000
        )
        
        analysis = response.choices[0].message.content
        
        return jsonify({
            'success': True,
            'analysis': analysis
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
