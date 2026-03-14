from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
import random
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-this-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bank.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# !! Change this — must match the password in myATM.cfg on your server !!
ATM_API_KEY = 'Change-This-Password'

# The admin username
ADMIN_USERNAME = 'Admin'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)


# ── Models ────────────────────────────────────────────────────────────────────

class User(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(20), unique=True, nullable=False)
    password       = db.Column(db.String(60), nullable=False)
    account_number = db.Column(db.String(8),  unique=True, nullable=False)
    balance        = db.Column(db.Integer, default=0)
    is_activated   = db.Column(db.Boolean, default=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    cards          = db.relationship('Card', backref='owner', lazy=True)

class Transaction(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    sender   = db.Column(db.String(8),  nullable=False)
    receiver = db.Column(db.String(8),  nullable=False)
    amount   = db.Column(db.Integer,    nullable=False)
    date     = db.Column(db.DateTime,   default=datetime.utcnow)
    note     = db.Column(db.String(64), default='')

class Card(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_number = db.Column(db.String(16), unique=True, nullable=True)
    cvv         = db.Column(db.String(3),  nullable=False)
    pin_hash    = db.Column(db.String(60), nullable=False)
    created_at  = db.Column(db.DateTime,  default=datetime.utcnow)

class SystemStats(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    physical_coins = db.Column(db.Integer, default=0)

with app.app_context():
    db.create_all()


# ── Helpers ───────────────────────────────────────────────────────────────────

def generate_account():
    while True:
        acc = str(random.randint(10000000, 99999999))
        if not User.query.filter_by(account_number=acc).first():
            return acc

def generate_card_number():
    while True:
        num = '4' + ''.join(str(random.randint(0, 9)) for _ in range(15))
        if not Card.query.filter_by(card_number=num).first():
            return num

def cleanup_expired():
    limit = datetime.utcnow() - timedelta(hours=12)
    for u in User.query.filter(User.is_activated == False, User.created_at < limit).all():
        db.session.delete(u)
    db.session.commit()

def is_admin():
    u = db.session.get(User, session.get('user_id'))
    return u and u.username == ADMIN_USERNAME


# ── Web routes ────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    cleanup_expired()
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    history = Transaction.query.filter(
        (Transaction.sender == user.account_number) |
        (Transaction.receiver == user.account_number)
    ).order_by(Transaction.date.desc()).all()
    accounts = {'BANK': 'SYSTEM'}
    for u in User.query.all():
        accounts[u.account_number] = u.username
    card = Card.query.filter_by(user_id=user.id).first()
    expire_time = (user.created_at + timedelta(hours=12)).isoformat()
    return render_template('dashboard.html', user=user, history=history,
                           accounts=accounts, card=card, expire_time=expire_time)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('User already exists')
            return redirect(url_for('register'))
        if password != request.form['confirm_password']:
            flash('Passwords do not match')
            return redirect(url_for('register'))
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        db.session.add(User(username=username, password=hashed,
                            account_number=generate_account()))
        db.session.commit()
        flash('Registered! Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and bcrypt.check_password_hash(user.password, request.form['password']):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/send', methods=['POST'])
def send():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if not user or not user.is_activated:
        return redirect(url_for('index'))
    receiver = User.query.filter_by(account_number=request.form.get('receiver_acc')).first()
    try:
        amount = int(request.form.get('amount', 0))
    except ValueError:
        return redirect(url_for('index'))
    if receiver and receiver.account_number != user.account_number and user.balance >= amount > 0:
        user.balance -= amount
        receiver.balance += amount
        db.session.add(Transaction(sender=user.account_number,
                                   receiver=receiver.account_number, amount=amount))
        db.session.commit()
    return redirect(url_for('index'))


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.route('/admin')
def admin():
    cleanup_expired()
    if not is_admin():
        return 'Access Denied', 403
    users = User.query.all()
    total = sum(u.balance for u in users)
    stats = SystemStats.query.first() or SystemStats(physical_coins=0)
    if not SystemStats.query.first():
        db.session.add(stats)
        db.session.commit()
    cards = {c.user_id: c for c in Card.query.all()}
    return render_template('admin.html', users=users, total_balance=total,
                           physical_coins=stats.physical_coins, cards=cards)

@app.route('/admin/update_physical', methods=['POST'])
def update_physical():
    if not is_admin(): return 'Access Denied', 403
    stats = SystemStats.query.first()
    if stats:
        try: stats.physical_coins = max(0, int(request.form.get('amount', 0)))
        except ValueError: pass
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/deposit/<int:uid>', methods=['POST'])
def admin_deposit(uid):
    if not is_admin(): return 'Access Denied', 403
    user = db.session.get(User, uid)
    try: amount = int(request.form.get('amount', 0))
    except ValueError: amount = 0
    if user and amount > 0:
        user.balance += amount
        user.is_activated = True
        db.session.add(Transaction(sender='BANK', receiver=user.account_number, amount=amount))
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/withdraw/<int:uid>', methods=['POST'])
def admin_withdraw(uid):
    if not is_admin(): return 'Access Denied', 403
    user = db.session.get(User, uid)
    try: amount = int(request.form.get('amount', 0))
    except ValueError: amount = 0
    if user and amount > 0 and user.balance >= amount:
        user.balance -= amount
        db.session.add(Transaction(sender=user.account_number, receiver='BANK', amount=amount))
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:uid>', methods=['POST'])
def admin_delete(uid):
    if not is_admin(): return 'Access Denied', 403
    user = db.session.get(User, uid)
    if user and user.username != ADMIN_USERNAME:
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/history/<int:uid>')
def admin_history(uid):
    if not is_admin(): return 'Access Denied', 403
    user = db.session.get(User, uid)
    if not user: return redirect(url_for('admin'))
    history = Transaction.query.filter(
        (Transaction.sender == user.account_number) |
        (Transaction.receiver == user.account_number)
    ).order_by(Transaction.date.desc()).all()
    accounts = {'BANK': 'SYSTEM'}
    for u in User.query.all():
        accounts[u.account_number] = u.username
    card = Card.query.filter_by(user_id=user.id).first()
    return render_template('admin_history.html', target_user=user,
                           history=history, accounts=accounts, card=card)

@app.route('/admin/delete_tx/<int:tx_id>/<int:uid>', methods=['POST'])
def admin_delete_tx(tx_id, uid):
    if not is_admin(): return 'Access Denied', 403
    tx = db.session.get(Transaction, tx_id)
    if tx:
        db.session.delete(tx)
        db.session.commit()
    return redirect(url_for('admin_history', uid=uid))


# ── MyATM Mod API ─────────────────────────────────────────────────────────────

def check_key(data):
    return data.get('api_password') == ATM_API_KEY

@app.route('/api/atm', methods=['POST'])
def api_atm():
    """
    Called by the ATM block in-game.
    Body: { api_password, type="ATM", login, password, pin }
    Returns: { success, card_number, cvv } or { success: false, message }
    """
    data = request.get_json(silent=True)
    if not data or not check_key(data) or data.get('type') != 'ATM':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    login    = data.get('login', '').strip()
    password = data.get('password', '')
    pin      = str(data.get('pin', '')).strip()

    if not login or not password or not pin:
        return jsonify({'success': False, 'message': 'Missing fields'}), 400
    if not pin.isdigit() or len(pin) < 4:
        return jsonify({'success': False, 'message': 'PIN must be 4+ digits'}), 400

    user = User.query.filter_by(username=login).first()
    if not user or not bcrypt.check_password_hash(user.password, password):
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
    if not user.is_activated:
        return jsonify({'success': False, 'message': 'Account not activated'}), 403

    card = Card.query.filter_by(user_id=user.id).first()
    if card:
        if not bcrypt.check_password_hash(card.pin_hash, pin):
            return jsonify({'success': False, 'message': 'Wrong PIN'}), 401
        return jsonify({'success': True, 'card_number': card.card_number, 'cvv': card.cvv})
    else:
        card_number = generate_card_number()
        cvv         = str(random.randint(100, 999))
        pin_hash    = bcrypt.generate_password_hash(pin).decode('utf-8')
        db.session.add(Card(user_id=user.id, card_number=card_number,
                            cvv=cvv, pin_hash=pin_hash))
        db.session.commit()
        return jsonify({'success': True, 'card_number': card_number, 'cvv': cvv})

@app.route('/api/terminal', methods=['POST'])
def api_terminal():
    """
    Called by the Terminal block in-game.
    Body: { api_password, type="TERMINAL", card_number, cvv, receiver_account, amount, pin }
    Returns: { success: true, message: "DONE" } or { success: false, message }
    """
    data = request.get_json(silent=True)
    if not data or not check_key(data) or data.get('type') != 'TERMINAL':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    card_number      = data.get('card_number', '').strip()
    cvv              = str(data.get('cvv', '')).strip()
    receiver_account = data.get('receiver_account', '').strip()
    pin              = str(data.get('pin', '')).strip()
    try:
        amount = int(data.get('amount', 0))
        if amount <= 0: raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid amount'}), 400

    if not all([card_number, cvv, receiver_account, pin]):
        return jsonify({'success': False, 'message': 'Missing fields'}), 400

    card = Card.query.filter_by(card_number=card_number).first()
    if not card:
        return jsonify({'success': False, 'message': 'Card not found'}), 404
    if card.cvv != cvv:
        return jsonify({'success': False, 'message': 'Wrong CVV'}), 401
    if not bcrypt.check_password_hash(card.pin_hash, pin):
        return jsonify({'success': False, 'message': 'Wrong PIN'}), 401

    sender = db.session.get(User, card.user_id)
    if not sender or not sender.is_activated:
        return jsonify({'success': False, 'message': 'Sender account invalid'}), 403

    receiver = User.query.filter_by(account_number=receiver_account).first()
    if not receiver:
        return jsonify({'success': False, 'message': 'Receiver not found'}), 404
    if sender.account_number == receiver.account_number:
        return jsonify({'success': False, 'message': 'Cannot pay yourself'}), 400
    if sender.balance < amount:
        return jsonify({'success': False,
                        'message': f'Insufficient funds ({sender.balance})'}), 400

    sender.balance   -= amount
    receiver.balance += amount
    db.session.add(Transaction(sender=sender.account_number,
                               receiver=receiver.account_number,
                               amount=amount, note='Terminal payment'))
    db.session.commit()
    return jsonify({'success': True, 'message': 'DONE'})


if __name__ == '__main__':
    app.run(debug=True)
