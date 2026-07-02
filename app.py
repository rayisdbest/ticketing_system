from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for
from functools import wraps
from dotenv import load_dotenv
import os
import jwt
import datetime
import random
import json
import redis
import psycopg2
from psycopg2.extras import RealDictCursor
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.utils import secure_filename
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

load_dotenv()

app = Flask(__name__)
CORS(app) # Prevents cross-origin block issues during JS API calls

# Configs
SECRET_KEY = os.getenv('JWT_SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY is not set in .env file!")

# Automatically connects to Docker PostgreSQL fallback or local instance
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://postgres:secure_password@localhost:5432/tickets_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'uploads')

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# ====================== ROLE CONFIG ======================
ADMIN_EMAILS = {"imran.sattar@nagariatextiles.com", "manager@nagariatextiles.com"}
IT_AGENT_EMAILS = {"tech1@nagariatextiles.com", "support@nagariatextiles.com"}

redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)


# ====================== DATABASE MODEL (SQLAlchemy) ======================
class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_name = db.Column(db.String(100), nullable=True)
    requester_email = db.Column(db.String(120), nullable=True)
    subject = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.String(20), nullable=False)
    group = db.Column(db.String(50), default='General')
    status = db.Column(db.String(20), default='Open')
    assigned_agent = db.Column(db.String(50), nullable=True)
    sla_breached = db.Column(db.Integer, default=0) 
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    attachment_filename = db.Column(db.String(255), nullable=True)
    verification_code = db.Column(db.String(6), nullable=True)
    is_validated = db.Column(db.Boolean, default=False)

# Auto-initialize PostgreSQL Tables inside app context
with app.app_context():
    db.create_all()


# ====================== UNIFIED POSTGRESQL HELPER ======================
def get_db_connection():
    # Routes analytics connections to the identical PostgreSQL URI
    conn = psycopg2.connect(app.config['SQLALCHEMY_DATABASE_URI'])
    return conn


# ====================== JWT TOKEN DECORATOR ======================
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            try:
                token = request.headers['Authorization'].split(" ")[1]
            except IndexError:
                return jsonify({"error": "Malformed Authorization Header Token!"}), 401

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


# ====================== FRONTEND WEB VIEW RENDERS ======================

@app.route('/')
def index_redirect():
    return redirect(url_for('login_page'))

@app.route('/login.html')
def login_page():
    return render_template('login.html')

@app.route('/Admin_dashboard.html')
def admin_dashboard_page():
    return render_template('Admin_dashboard.html')

@app.route('/reports.html')
def reports_page():
    return render_template('reports.html')

@app.route('/submit_ticket.html')
def submit_ticket_page():
    return render_template('submit_ticket.html')

@app.route('/view_tickets.html')
def view_tickets_page():
    tickets = Ticket.query.order_by(Ticket.created_at.desc()).all()
    return render_template('view_tickets.html', tickets=tickets)


# ====================== API DATA ENDPOINTS ======================

@app.route('/api/dashboard/stats', methods=['GET'])
@token_required
def dashboard_stats(current_user):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT COUNT(*) as total FROM ticket")
    total = cursor.fetchone()['total'] or 0

    cursor.execute("SELECT COUNT(*) as resolved FROM ticket WHERE status = 'Resolved'")
    resolved = cursor.fetchone()['resolved'] or 0

    cursor.execute("SELECT COUNT(*) as unresolved FROM ticket WHERE status != 'Resolved'")
    unresolved = cursor.fetchone()['unresolved'] or 0

    cursor.execute("SELECT COUNT(*) as in_sla FROM ticket WHERE status = 'Resolved' AND sla_breached = 0")
    resolved_in_sla = cursor.fetchone()['in_sla'] or 0

    cursor.execute("SELECT COUNT(*) as outside_sla FROM ticket WHERE status = 'Resolved' AND sla_breached = 1")
    resolved_outside_sla = cursor.fetchone()['outside_sla'] or 0

    hourly_received = [0] * 24
    hourly_resolved_in_sla = [0] * 24
    hourly_resolved_outside_sla = [0] * 24

    # Adjusted to standard PostgreSQL date/time extraction syntax
    cursor.execute("""
        SELECT EXTRACT(HOUR FROM created_at)::INTEGER as hour, COUNT(*) as count 
        FROM ticket 
        GROUP BY hour
    """)
    for row in cursor.fetchall():
        if row['hour'] is not None and 0 <= row['hour'] < 24:
            hourly_received[row['hour']] = row['count']

    cursor.execute("""
        SELECT EXTRACT(HOUR FROM resolved_at)::INTEGER as hour, COUNT(*) as count 
        FROM ticket 
        WHERE status = 'Resolved' AND sla_breached = 0
        GROUP BY hour
    """)
    for row in cursor.fetchall():
        if row['hour'] is not None and 0 <= row['hour'] < 24:
            hourly_resolved_in_sla[row['hour']] = row['count']

    cursor.execute("""
        SELECT EXTRACT(HOUR FROM resolved_at)::INTEGER as hour, COUNT(*) as count 
        FROM ticket 
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
        "unassigned": unresolved // 3 if unresolved > 0 else 0,
        "pending": unresolved // 2 if unresolved > 0 else 0,
        "overdue": unresolved // 6 if unresolved > 0 else 0,
        "due_today": 0,
        "due_tomorrow": 0,
        "resolved_in_sla": resolved_in_sla,
        "resolved_outside_sla": resolved_outside_sla,
        "avg_resolution_time": "14 min",
        "min_resolution_time": "2 min",
        "max_resolution_time": "45 min",
        "hourly_received": hourly_received,
        "hourly_resolved_in_sla": hourly_resolved_in_sla,
        "hourly_resolved_outside_sla": hourly_resolved_outside_sla
    }
    
    cursor.close()
    conn.close()
    return jsonify(stats)


@app.route('/api/tickets/submit', methods=['POST'])
@token_required
def submit_ticket(current_user):
    try:
        subject = request.form.get('subject')
        description = request.form.get('description')
        category = request.form.get('category')
        priority = request.form.get('priority')
        group = request.form.get('group', 'General')

        if not all([subject, category, priority]):
            return jsonify({"error": "Missing mandatory ticket form fields"}), 400

        file = request.files.get('file')
        filename = None
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        new_ticket = Ticket(
            requester_name=current_user.get('username'),
            requester_email=current_user.get('email'),
            subject=subject,
            description=description or '',
            category=category,
            priority=priority,
            group=group,
            attachment_filename=filename
        )
        db.session.add(new_ticket)
        db.session.commit()
        return jsonify({"message": "Ticket created successfully", "ticket_id": new_ticket.id})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"An infrastructure error occurred: {str(e)}"}), 500


@app.route('/api/tickets/resolve/<int:ticket_id>', methods=['POST'])
@token_required
def resolve_ticket(current_user, ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    ticket.status = 'Resolved'
    ticket.resolved_at = datetime.datetime.utcnow()
    
    if ticket.created_at and (ticket.resolved_at - ticket.created_at).total_seconds() > 86400:
        ticket.sla_breached = 1
        
    db.session.commit()
    return jsonify({"message": f"Ticket #{ticket_id} marked as Resolved"})


@app.route('/api/tickets/reopen/<int:ticket_id>', methods=['POST'])
@token_required
def reopen_ticket(current_user, ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    ticket.status = 'Open'
    ticket.resolved_at = None
    ticket.sla_breached = 0
    db.session.commit()
    return jsonify({"message": f"Ticket #{ticket_id} re-opened successfully"})


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


# ====================== FILE ASSET ROUTING ======================
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == '__main__':
    app.run(debug=True, port=5000)