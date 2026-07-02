from flask import Flask, request, jsonify
from functools import wraps
from dotenv import load_dotenv
import os
import jwt
import datetime
import random
import json
import redis
import sqlite3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

load_dotenv()

app = Flask(__name__)
SECRET_KEY = os.getenv('JWT_SECRET_KEY')

if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY is not set in .env file!")

# ====================== ROLE CONFIG ======================
ADMIN_EMAILS = {"imran.sattar@nagariatextiles.com", "manager@nagariatextiles.com"}
IT_AGENT_EMAILS = {"tech1@nagariatextiles.com", "support@nagariatextiles.com"}

redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# ====================== DATABASE HELPER ======================
def get_db_connection():
    conn = sqlite3.connect('tickets.db')
    conn.row_factory = sqlite3.Row
    return conn

# ====================== JWT TOKEN DECORATOR ======================
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]

        if not token:
            return jsonify({"error": "Token is missing!"}), 401

        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired!"}), 401
        except:
            return jsonify({"error": "Invalid token!"}), 401

        return f(current_user, *args, **kwargs)
    return decorated

# ====================== EMAIL FUNCTION ======================
def send_otp_email(email, otp):
    sender_email = os.getenv('EMAIL_ADDRESS')
    sender_password = os.getenv('EMAIL_PASSWORD')

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = email
    msg['Subject'] = "Your Nagaria Textiles Login Code"

    body = f"Your OTP is: {otp}\n\nThis code expires in 10 minutes."
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print("Email error:", e)
        return False


# ====================== DASHBOARD STATS (Updated for Chart) ======================
# ====================== DASHBOARD STATS (Fully Dynamic with Graphs) ======================
@app.route('/api/dashboard/stats', methods=['GET'])
@token_required
def dashboard_stats(current_user):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Basic Box Counts
    cursor.execute("SELECT COUNT(*) as total FROM tickets")
    total = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) as resolved FROM tickets WHERE status = 'Resolved'")
    resolved = cursor.fetchone()['resolved']

    cursor.execute("SELECT COUNT(*) as unresolved FROM tickets WHERE status != 'Resolved'")
    unresolved = cursor.fetchone()['unresolved']

    # 2. SLA Stats
    cursor.execute("SELECT COUNT(*) as in_sla FROM tickets WHERE status = 'Resolved' AND sla_breached = 0")
    resolved_in_sla = cursor.fetchone()['in_sla']

    cursor.execute("SELECT COUNT(*) as outside_sla FROM tickets WHERE status = 'Resolved' AND sla_breached = 1")
    resolved_outside_sla = cursor.fetchone()['outside_sla']

    # 3. Initialize empty 24-hour arrays (indices 0 to 23)
    hourly_received = [0] * 24
    hourly_resolved_in_sla = [0] * 24
    hourly_resolved_outside_sla = [0] * 24

    # 4. QUERY LIVE HOURLY DATA FROM DATABASE
    
    # Get hourly distribution of Received tickets based on created_at
    cursor.execute("""
        SELECT CAST(strftime('%H', created_at) AS INTEGER) as hour, COUNT(*) as count 
        FROM tickets 
        GROUP BY hour
    """)
    for row in cursor.fetchall():
        if row['hour'] is not None and 0 <= row['hour'] < 24:
            hourly_received[row['hour']] = row['count']

    # Get hourly distribution of Resolved within SLA tickets
    cursor.execute("""
        SELECT CAST(strftime('%H', resolved_at) AS INTEGER) as hour, COUNT(*) as count 
        FROM tickets 
        WHERE status = 'Resolved' AND sla_breached = 0
        GROUP BY hour
    """)
    for row in cursor.fetchall():
        if row['hour'] is not None and 0 <= row['hour'] < 24:
            hourly_resolved_in_sla[row['hour']] = row['count']

    # Get hourly distribution of Resolved outside SLA tickets
    cursor.execute("""
        SELECT CAST(strftime('%H', resolved_at) AS INTEGER) as hour, COUNT(*) as count 
        FROM tickets 
        WHERE status = 'Resolved' AND sla_breached = 1
        GROUP BY hour
    """)
    for row in cursor.fetchall():
        if row['hour'] is not None and 0 <= row['hour'] < 24:
            hourly_resolved_outside_sla[row['hour']] = row['count']

    stats = {
        "received": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "unassigned": 0,
        "pending": 0,
        "overdue": 0,
        "due_today": 0,
        "due_tomorrow": 0,
        "resolved_in_sla": resolved_in_sla,
        "resolved_outside_sla": resolved_outside_sla,
        "avg_resolution_time": "0 min",
        "min_resolution_time": "0 min",
        "max_resolution_time": "0 min",
        
        # Live 24-hour data sent straight to Chart.js
        "hourly_received": hourly_received,
        "hourly_resolved_in_sla": hourly_resolved_in_sla,
        "hourly_resolved_outside_sla": hourly_resolved_outside_sla
    }
    
    conn.close()
    return jsonify(stats)

# ====================== AUTH ROUTES ======================
@app.route('/request-otp', methods=['POST'])
def request_otp():
    data = request.json
    email = data.get('email')

    if not email or not email.endswith('@nagariatextiles.com'):
        return jsonify({"error": "Only @nagariatextiles.com emails allowed"}), 403

    otp = random.randint(100000, 999999)
    otp_data = {"otp": otp}

    redis_client.set(f"otp:{email}", json.dumps(otp_data), ex=600)

    if send_otp_email(email, otp):
        return jsonify({"message": "OTP sent successfully", "email": email})
    return jsonify({"error": "Failed to send OTP"}), 500


@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    data = request.json
    email = data.get('email')
    otp_input = data.get('otp')
    username = data.get('username')

    if not all([email, otp_input, username]):
        return jsonify({"error": "Missing fields"}), 400

    otp_json = redis_client.get(f"otp:{email}")
    if not otp_json:
        return jsonify({"error": "OTP expired"}), 400

    if str(json.loads(otp_json)['otp']) != str(otp_input):
        return jsonify({"error": "Invalid OTP"}), 400

    role = "ADMINISTRATOR" if email in ADMIN_EMAILS else \
           "IT_AGENT" if email in IT_AGENT_EMAILS else "USER"

    now = datetime.datetime.now(datetime.timezone.utc)

    token = jwt.encode({
        "sub": email,
        "email": email,
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(hours=12)).timestamp())
    }, SECRET_KEY, algorithm="HS256")

    redis_client.delete(f"otp:{email}")

    return jsonify({
        "message": "Login successful",
        "token": token,
        "username": username,
        "email": email,
        "role": role
    })


# ====================== FRONTEND ROUTES ======================
@app.route('/')
def home():
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>index.html not found</h1>", 404


if __name__ == '__main__':
    app.run(debug=True)