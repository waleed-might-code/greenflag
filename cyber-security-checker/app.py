from flask import Flask, render_template, request, jsonify
import os
from dotenv import load_dotenv
import hashlib
import re

load_dotenv()

app = Flask(__name__)

def analyze_cyber_security(username):
    """Analyze username and return security score with fun feedback"""
    
    # Calculate a pseudo-random score based on username
    hash_val = int(hashlib.md5(username.lower().encode()).hexdigest(), 16)
    base_score = (hash_val % 70) + 20  # Score between 20-90
    
    # Adjust score based on patterns
    score = base_score
    risks = []
    strengths = []
    
    # Check for common patterns
    if re.search(r'\d{4}', username):
        score -= 10
        risks.append("Birth year detected - hackers love easy guesses")
    
    if any(word in username.lower() for word in ['admin', 'root', 'user', 'test']):
        score -= 15
        risks.append("Generic username - you're basically wearing a 'hack me' sign")
    
    if len(username) < 6:
        score -= 10
        risks.append("Short username - even my grandma could brute force this")
    
    if re.search(r'[!@#$%^&*]', username):
        score += 10
        strengths.append("Special characters detected - nice touch!")
    
    if len(username) > 12:
        score += 5
        strengths.append("Long username - making hackers work for it")
    
    if username.lower() == username or username.upper() == username:
        score -= 5
        risks.append("No mixed case - predictable patterns detected")
    else:
        strengths.append("Mixed case - adding some spice")
    
    # Cap score between 0-100
    score = max(0, min(100, score))
    
    # Generate verdict
    if score >= 80:
        verdict = "🛡️ CYBER FORTRESS"
        message = "You're basically a digital ninja. Hackers see your username and cry."
        color = "#10b981"
    elif score >= 60:
        verdict = "🔒 PRETTY SECURE"
        message = "Not bad! You'd survive most script kiddies, but watch out for the pros."
        color = "#3b82f6"
    elif score >= 40:
        verdict = "⚠️ VULNERABLE"
        message = "You're one phishing email away from trouble. Time to level up your game."
        color = "#f59e0b"
    else:
        verdict = "🚨 HACKABLE AF"
        message = "Hackers are literally lining up. Your security is held together by hopes and prayers."
        color = "#ef4444"
    
    return {
        'score': score,
        'verdict': verdict,
        'message': message,
        'color': color,
        'risks': risks if risks else ["No major red flags detected"],
        'strengths': strengths if strengths else ["Could use some improvement"]
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({'error': 'Please enter a username'}), 400
    
    if len(username) > 50:
        return jsonify({'error': 'Username too long'}), 400
    
    result = analyze_cyber_security(username)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
