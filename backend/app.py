from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import csv
from io import StringIO
from flask import make_response
from sqlalchemy import func, cast, Date
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# Use a secret key from environment or fallback to a default (not recommended for production)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret-key-replace-me")

# Session Security Configuration
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevents JavaScript access to cookies
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # Protection against CSRF
app.config['SESSION_COOKIE_SECURE'] = False      # Set to True if using HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes


# Database configuration
db_path = os.path.join(os.path.dirname(__file__), 'biometrie.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Morocco Time Helper
def get_morocco_time():
    # Morocco is UTC+1
    return datetime.now(timezone(timedelta(hours=1)))

# Access Model
class Access(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    finger_id = db.Column(db.Integer, nullable=False)
    confidence = db.Column(db.Integer, nullable=False)
    is_authorized = db.Column(db.Boolean, default=True)
    prediction_result = db.Column(db.String(50), default="Normal")
    timestamp = db.Column(db.DateTime, default=get_morocco_time)

    def to_dict(self):
        return {
            "id": self.id,
            "finger_id": self.finger_id,
            "confidence": self.confidence,
            "is_authorized": self.is_authorized,
            "prediction_result": self.prediction_result,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }

# User Model (To map ID -> Name)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True) # fingerprint_id
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), default="Employee") # Admin, Employee, Visitor
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_morocco_time)

    def to_dict(self):
        return {
            "id": self.id, 
            "name": self.name, 
            "role": self.role, 
            "is_active": self.is_active
        }
# Admin Model
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

# Login Required Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Initialize database
with app.app_context():
    db.create_all()
    # Create default admin if not exists
    if not Admin.query.filter_by(username='admin').first():
        # Get password from environment or use a default for first-time setup
        initial_password = os.getenv("INITIAL_ADMIN_PASSWORD", "admin")
        hashed_password = generate_password_hash(initial_password)
        default_admin = Admin(username='admin', password=hashed_password)
        db.session.add(default_admin)
        db.session.commit()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and check_password_hash(admin.password, password):
            session['admin_id'] = admin.id
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Identifiants invalides")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin_id', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    # Fetch latest 20 access logs
    access_logs = Access.query.order_by(Access.timestamp.desc()).limit(20).all()
    return render_template('index.html', logs=access_logs)

@app.route('/access', methods=['POST'])
def register_access():
    # Temporairement désactivé pour test PowerShell
    # if not api_key or api_key != expected_key:
    #     return jsonify({"error": "Unauthorized hardware access"}), 401
        
    data = request.json
    if not data or 'fingerID' not in data or 'confidence' not in data:
        return jsonify({"error": "Invalid data"}), 400
    
    finger_id = data['fingerID']
    confidence = data['confidence']
    
    # 1. Logic by Role
    user = User.query.get(finger_id)
    is_authorized = False
    prediction = "Normal"
    
    if not user:
        prediction = "Inconnu"
    elif not user.is_active:
        prediction = "Compte Inactif"
    else:
        # Rules based on roles
        if user.role == "Administrateur":
            is_authorized = True
            prediction = "Admin Access"
            
        elif user.role == "Employé":
            if confidence >= 80:
                is_authorized = True
            else:
                prediction = "Confiance Faible"
                
        elif user.role == "Visiteur":
            now_hour = get_morocco_time().hour
            if 8 <= now_hour < 18:
                is_authorized = True
            else:
                prediction = "Hors Horaires"
        
        else:
            # Fallback for unknown roles
            is_authorized = True

    # 2. Additional simulation check (from previous version)
    if is_authorized and confidence < 50:
        prediction = "Alerte: Score Limite"

    new_access = Access(
        finger_id=finger_id,
        confidence=confidence,
        is_authorized=is_authorized,
        prediction_result=prediction
    )
    db.session.add(new_access)
    db.session.commit()
    
    return jsonify({
        "success": True, 
        "message": "Access registered",
        "authorized": is_authorized,
        "prediction": prediction
    }), 201

@app.route('/api/history', methods=['GET'])
@login_required
def get_history():
    logs = Access.query.order_by(Access.timestamp.desc()).limit(20).all()
    results = []
    for log in logs:
        # Find user name
        user = User.query.get(log.finger_id)
        name = user.name if user else f"Inconnu (ID #{log.finger_id})"
        
        d = log.to_dict()
        d['user_name'] = name
        results.append(d)
        
    return jsonify(results)

@app.route('/api/users', methods=['GET', 'POST'])
# @login_required  <-- Désactivé pour test PowerShell
def manage_users():
    if request.method == 'POST':
        # Create new user: {"name": "Alice"}
        data = request.json
        name = data.get('name')
        role = data.get('role', 'Employee')
        
        # Uniqueness check (Vérifier l'unicité)
        existing = User.query.filter_by(name=name).first()
        if existing:
            return jsonify({"error": "Nom déjà utilisé"}), 400

        # Find next free ID
        last_user = User.query.order_by(User.id.desc()).first()
        next_id = 1 if not last_user else last_user.id + 1
        
        if next_id > 127: return jsonify({"error": "Mémoire pleine"}), 400
        
        new_user = User(id=next_id, name=name, role=role)
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({"success": True, "user": new_user.to_dict()})
        
    else:
        users = User.query.all()
        return jsonify([u.to_dict() for u in users])

@app.route('/api/users/<int:user_id>', methods=['PUT', 'DELETE'])
@login_required
def detail_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'DELETE':
        # Trigger delete in sensor too (via command queue)
        global current_command
        current_command = {"action": "delete", "id": user_id}
        
        db.session.delete(user)
        db.session.commit()
        return jsonify({"success": True, "message": "User deleted and command sent"})
    
    elif request.method == 'PUT':
        data = request.json
        if 'name' in data: user.name = data['name']
        if 'role' in data: user.role = data['role']
        if 'is_active' in data: user.is_active = data['is_active']
        
        db.session.commit()
        return jsonify({"success": True, "user": user.to_dict()})

# --- COMMAND QUEUE FOR ESP32 ---
current_command = {"action": "wait", "id": 0}

@app.route('/api/command', methods=['GET', 'POST'])
def command_route():
    global current_command
    
    if request.method == 'POST':
        data = request.json
        current_command = data
        return jsonify({"status": "updated", "command": current_command})
    
    else:
        cmd_str = f"{current_command.get('action', 'wait').upper()}:{current_command.get('id', 0)}"
        return cmd_str

# --- HR & STATISTICS ENDPOINTS ---

@app.route('/api/work_hours', methods=['GET'])
@login_required
def get_work_hours():
    # Group by user and date, find min and max timestamp for "Authorized" scans
    # Only for the last 7 days
    seven_days_ago = get_morocco_time() - timedelta(days=7)
    
    results = db.session.query(
        Access.finger_id,
        func.date(Access.timestamp).label('date'),
        func.min(Access.timestamp).label('clock_in'),
        func.max(Access.timestamp).label('clock_out')
    ).filter(
        Access.is_authorized == True,
        Access.timestamp >= seven_days_ago
    ).group_by(
        Access.finger_id,
        func.date(Access.timestamp)
    ).all()

    work_data = []
    for r in results:
        user = User.query.get(r.finger_id)
        name = user.name if user else f"ID #{r.finger_id}"
        
        # Calculate duration
        duration = r.clock_out - r.clock_in
        hours = duration.total_seconds() / 3600
        
        work_data.append({
            "name": name,
            "date": str(r.date),
            "clock_in": r.clock_in.strftime("%H:%M:%S"),
            "clock_out": r.clock_out.strftime("%H:%M:%S"),
            "duration": f"{hours:.2f}h"
        })
    
    return jsonify(work_data)

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    # 1. Peak Attendance (counts per hour)
    peaks = db.session.query(
        func.strftime('%H', Access.timestamp).label('hour'),
        func.count(Access.id).label('count')
    ).group_by('hour').all()
    
    peak_data = {str(h).zfill(2): count for h, count in peaks}
    
    # 2. Success vs Failure rate
    success_count = Access.query.filter_by(is_authorized=True).count()
    failure_count = Access.query.filter_by(is_authorized=False).count()
    
    return jsonify({
        "peaks": peak_data,
        "rates": {
            "success": success_count,
            "failure": failure_count
        }
    })

@app.route('/api/export/csv', methods=['GET'])
@login_required
def export_csv():
    logs = Access.query.order_by(Access.timestamp.desc()).all()
    
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'FingerID', 'User Name', 'Confidence', 'Authorized', 'Result', 'Timestamp'])
    
    for log in logs:
        user = User.query.get(log.finger_id)
        name = user.name if user else "Inconnu"
        cw.writerow([
            log.id, 
            log.finger_id, 
            name, 
            log.confidence, 
            log.is_authorized, 
            log.prediction_result, 
            log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        ])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=historique_biometrie.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# --- ACTIVE USERS MANAGEMENT ---
active_users = []

@app.route('/api/active_users', methods=['GET', 'POST'])
def active_users_route():
    global active_users
    if request.method == 'POST':
        data = request.json
        if 'ids' in data:
            active_users = data['ids']
            active_users.sort()
        return jsonify({"status": "updated", "count": len(active_users)})
    else:
        results = []
        for uid in active_users:
            user = User.query.get(uid)
            results.append({
                "id": uid,
                "name": user.name if user else f"Inconnu",
                "role": user.role if user else "Unknown",
                "is_active": user.is_active if user else False
            })
        return jsonify(results)

if __name__ == '__main__':
    # Security: Binding to 127.0.0.1 (Localhost) ensures only local processes (like the bridge)
    # can talk to Flask, protecting port 5000 from the external network.
    app.run(host='127.0.0.1', port=5000, debug=True)
