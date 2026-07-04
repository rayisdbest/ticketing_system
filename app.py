from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for
from functools import wraps
from dotenv import load_dotenv
import os
import jwt
import datetime
from datetime import timedelta
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
    # Capture start_date and end_date inputs from the calendar elements
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    overview_mode = request.args.get('overview', 'tickets')

    # Default bounds if calendar elements are unpopulated
    now_utc = datetime.datetime.utcnow()
    if start_date_str:
        start_bound = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
    else:
        start_bound = now_utc - timedelta(days=7)

    if end_date_str:
        end_bound = datetime.datetime.strptime(end_date_str, "%Y-%m-%d")
        # Extend to end of day boundary (23:59:59)
        end_bound = end_bound.replace(hour=23, minute=59, second=59)
    else:
        end_bound = now_utc.replace(hour=23, minute=59, second=59)

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Received Tickets within time bounds
    cursor.execute("SELECT COUNT(*) as total FROM ticket WHERE created_at BETWEEN %s AND %s", (start_bound, end_bound))
    received_count = cursor.fetchone()['total'] or 0

    # 2. Resolved Tickets within time bounds
    cursor.execute("SELECT COUNT(*) as resolved FROM ticket WHERE status = 'Resolved' AND resolved_at BETWEEN %s AND %s", (start_bound, end_bound))
    resolved_count = cursor.fetchone()['total'] if False else (cursor.fetchone() or {'resolved': 0})['resolved']

    # 3. Unresolved Tickets (Any ticket currently not resolved created within timeframe)
    cursor.execute("SELECT COUNT(*) as unresolved FROM ticket WHERE status != 'Resolved' AND created_at BETWEEN %s AND %s", (start_bound, end_bound))
    unresolved_count = cursor.fetchone()['unresolved'] or 0

    # 4. Unassigned Tickets (Unresolved tickets without agent assigned)
    cursor.execute("SELECT COUNT(*) as unassigned FROM ticket WHERE status != 'Resolved' AND assigned_agent IS NULL AND created_at BETWEEN %s AND %s", (start_bound, end_bound))
    unassigned_count = cursor.fetchone()['unassigned'] or 0

    # 5. Pending Tickets
    cursor.execute("SELECT COUNT(*) as pending FROM ticket WHERE status = 'Pending' AND created_at BETWEEN %s AND %s", (start_bound, end_bound))
    pending_count = cursor.fetchone()['pending'] or 0

    # 6. Overdue Tickets (SLA Breached and unresolved)
    cursor.execute("SELECT COUNT(*) as overdue FROM ticket WHERE status != 'Resolved' AND sla_breached = 1 AND created_at BETWEEN %s AND %s", (start_bound, end_bound))
    overdue_count = cursor.fetchone()['overdue'] or 0

    # 7. Due Today (Mocked or evaluated using target limits)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now_utc.replace(hour=23, minute=59, second=59, microsecond=999)
    cursor.execute("SELECT COUNT(*) as due_today FROM ticket WHERE status != 'Resolved' AND created_at BETWEEN %s AND %s", (today_start, today_end))
    due_today_count = cursor.fetchone()['due_today'] or 0

    # 8. Due Tomorrow (Next calendar date metrics calculation)
    tomorrow_start = today_start + timedelta(days=1)
    tomorrow_end = today_end + timedelta(days=1)
    cursor.execute("SELECT COUNT(*) as due_tomorrow FROM ticket WHERE status != 'Resolved' AND created_at BETWEEN %s AND %s", (tomorrow_start, tomorrow_end))
    due_tomorrow_count = cursor.fetchone()['due_tomorrow'] or 0

    # SLA Analytics Box values
    cursor.execute("SELECT COUNT(*) as in_sla FROM ticket WHERE status = 'Resolved' AND sla_breached = 0 AND resolved_at BETWEEN %s AND %s", (start_bound, end_bound))
    resolved_in_sla = cursor.fetchone()['in_sla'] or 0

    cursor.execute("SELECT COUNT(*) as outside_sla FROM ticket WHERE status = 'Resolved' AND sla_breached = 1 AND resolved_at BETWEEN %s AND %s", (start_bound, end_bound))
    resolved_outside_sla = cursor.fetchone()['outside_sla'] or 0

    # Chart Processing Logic: Generate dynamic labels day-by-day based on duration gap
    delta_days = (end_bound - start_bound).days
    
    if delta_days <= 1:
        # Hour-by-hour view for short targets
        chart_labels = [f"{h}:00" for h in range(24)]
        received_data = [0] * 24
        in_sla_data = [0] * 24
        out_sla_data = [0] * 24

        cursor.execute("SELECT EXTRACT(HOUR FROM created_at)::INTEGER as step, COUNT(*) as count FROM ticket WHERE created_at BETWEEN %s AND %s GROUP BY step", (start_bound, end_bound))
        for row in cursor.fetchall():
            if row['step'] is not None and 0 <= row['step'] < 24: received_data[row['step']] = row['count']

        cursor.execute("SELECT EXTRACT(HOUR FROM resolved_at)::INTEGER as step, COUNT(*) as count FROM ticket WHERE status = 'Resolved' AND sla_breached = 0 AND resolved_at BETWEEN %s AND %s GROUP BY step", (start_bound, end_bound))
        for row in cursor.fetchall():
            if row['step'] is not None and 0 <= row['step'] < 24: in_sla_data[row['step']] = row['count']

        cursor.execute("SELECT EXTRACT(HOUR FROM resolved_at)::INTEGER as step, COUNT(*) as count FROM ticket WHERE status = 'Resolved' AND sla_breached = 1 AND resolved_at BETWEEN %s AND %s GROUP BY step", (start_bound, end_bound))
        for row in cursor.fetchall():
            if row['step'] is not None and 0 <= row['step'] < 24: out_sla_data[row['step']] = row['count']
    else:
        # Date-by-date matrix arrays mapping
        chart_labels = []
        for i in range(delta_days + 1):
            day_label = (start_bound + timedelta(days=i)).strftime("%b %d")
            chart_labels.append(day_label)
        
        received_data = [0] * len(chart_labels)
        in_sla_data = [0] * len(chart_labels)
        out_sla_data = [0] * len(chart_labels)

        cursor.execute("SELECT TO_CHAR(created_at, 'Mon DD') as step, COUNT(*) as count FROM ticket WHERE created_at BETWEEN %s AND %s GROUP BY step", (start_bound, end_bound))
        for row in cursor.fetchall():
            if row['step'] in chart_labels:
                received_data[chart_labels.index(row['step'])] = row['count']

        cursor.execute("SELECT TO_CHAR(resolved_at, 'Mon DD') as step, COUNT(*) as count FROM ticket WHERE status = 'Resolved' AND sla_breached = 0 AND resolved_at BETWEEN %s AND %s GROUP BY step", (start_bound, end_bound))
        for row in cursor.fetchall():
            if row['step'] in chart_labels:
                in_sla_data[chart_labels.index(row['step'])] = row['count']

        cursor.execute("SELECT TO_CHAR(resolved_at, 'Mon DD') as step, COUNT(*) as count FROM ticket WHERE status = 'Resolved' AND sla_breached = 1 AND resolved_at BETWEEN %s AND %s GROUP BY step", (start_bound, end_bound))
        for row in cursor.fetchall():
            if row['step'] in chart_labels:
                out_sla_data[chart_labels.index(row['step'])] = row['count']

    # Calculate Dynamic Resolution Time Analytics (in minutes)
    cursor.execute("""
        SELECT 
            COALESCE(AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))/60), 0)::INTEGER as avg_res,
            COALESCE(MIN(EXTRACT(EPOCH FROM (resolved_at - created_at))/60), 0)::INTEGER as min_res,
            COALESCE(MAX(EXTRACT(EPOCH FROM (resolved_at - created_at))/60), 0)::INTEGER as max_res
        FROM ticket 
        WHERE status = 'Resolved' AND resolved_at BETWEEN %s AND %s
    """, (start_bound, end_bound))
    
    res_metrics = cursor.fetchone()
    avg_res_time = f"{res_metrics['avg_res']} min"
    min_res_time = f"{res_metrics['min_res']} min"
    max_res_time = f"{res_metrics['max_res']} min"

    stats = {
        "received": received_count,
        "resolved": resolved_count,
        "unresolved": unresolved_count,
        "unassigned": unassigned_count,
        "pending": pending_count,
        "overdue": overdue_count,
        "due_today": due_today_count,
        "due_tomorrow": due_tomorrow_count,
        "resolved_in_sla": resolved_in_sla,
        "resolved_outside_sla": resolved_outside_sla,
        "avg_resolution_time": avg_res_time,
        "min_resolution_time": min_res_time,
        "max_resolution_time": max_res_time,
        "chart_labels": chart_labels,
        "chart_data": {
            "received": received_data,
            "resolved_in_sla": in_sla_data,
            "resolved_outside_sla": out_sla_data
        }
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