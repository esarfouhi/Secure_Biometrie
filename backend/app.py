from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = "supersecretkeyforbiometrie" # Change this in production
CORS(app)

# Database configuration
db_path = os.path.join(os.path.dirname(__file__), 'biometrie.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Access Model
class Access(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    finger_id = db.Column(db.Integer, nullable=False)
    confidence = db.Column(db.Integer, nullable=False)
    is_authorized = db.Column(db.Boolean, default=True)
    prediction_result = db.Column(db.String(50), default="Normal")
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
        hashed_password = generate_password_hash('admin')
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
            now_hour = datetime.now().hour
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
@login_required
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
    app.run(host='0.0.0.0', port=5000, debug=True)
