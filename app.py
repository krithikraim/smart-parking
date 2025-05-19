from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

from sqlalchemy.exc import IntegrityError

from datetime import datetime, timedelta


app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///parking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    __tablename__ = 'users'  # Add explicit table name
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='user')
    vehicle_number = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    bookings = db.relationship('Booking', backref='user', lazy=True)

class ParkingSlot(db.Model):
    __tablename__ = 'parking_slots'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default='available')
    hourly_rate = db.Column(db.Float, default=5.0)
    vehicle_type = db.Column(db.String(20), default='car')  # car, bike, truck
    bookings = db.relationship('Booking', backref='slot', lazy=True)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey('parking_slots.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    total_cost = db.Column(db.Float)
    status = db.Column(db.String(20), default='active')
    booked_hours = db.Column(db.Integer, nullable=False)
    expected_end_time = db.Column(db.DateTime, nullable=False)

def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return func(*args, **kwargs)
    return decorated_view

@app.route('/')
def default():
    return redirect(url_for('login'))
# Auth Routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        vehicle_number = request.form.get('vehicle_number')
        
        error = None
        if not username:
            error = 'Username is required'
        elif not password:
            error = 'Password is required'
        elif User.query.filter_by(username=username).first() is not None:
            error = f"Username {username} is already registered"
            
        if error is None:
            new_user = User(
                username=username,
                password_hash=generate_password_hash(password),
                vehicle_number=vehicle_number
            )
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please login', 'success')
            return redirect(url_for('login'))
        
        flash(error, 'danger')
    
    return render_template('register.html')

@app.route('/admin/reports')
@admin_required
def reports():
    # you can later replace this with real reporting logic
    return render_template('admin/reports.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            # send admins to /admin, everyone else to /dashboard
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('dashboard'))
        
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# @app.route('/dashboard')
# @login_required
# def dashboard():
#     # Get available parking slots
#     available_slots = ParkingSlot.query.filter_by(status='available').all()
    
#     # Fix active bookings query
#     active_bookings = Booking.query.filter_by(
#         user_id=current_user.id,
#         status='active'
#     ).join(ParkingSlot).all()

#     return render_template('dashboard.html', 
#                          available_slots=available_slots,
#                          active_bookings=active_bookings)


@app.route('/dashboard')
@login_required
def dashboard():
    # Get available parking slots
    available_slots = ParkingSlot.query.filter_by(status='available').all()
    
    # Count available slots by vehicle type
    # Make sure the available_slots count includes all vehicle types
    stats = {
        'total_slots': ParkingSlot.query.count(),
        'available_slots': ParkingSlot.query.filter_by(status='available').count(),
        # Add vehicle-specific counts for the modal
        'available_car_slots': ParkingSlot.query.filter_by(status='available', vehicle_type='car').count(),
        'available_bike_slots': ParkingSlot.query.filter_by(status='available', vehicle_type='bike').count(),
        'available_truck_slots': ParkingSlot.query.filter_by(status='available', vehicle_type='truck').count(),
        # ... other stats
    }
    
    # Fix active bookings query
    active_bookings = Booking.query.filter_by(
        user_id=current_user.id,
        status='active'
    ).join(ParkingSlot).all()

    return render_template('dashboard.html', 
                         available_slots=available_slots,
                         active_bookings=active_bookings,
                         stats=stats)  # Pass the stats to the template

@app.route('/book/<int:slot_id>', methods=['GET', 'POST'])
@login_required
def book_slot(slot_id):
    slot = ParkingSlot.query.get_or_404(slot_id)

    if request.method == 'POST':
        # Validate hours input
        try:
            hours = int(request.form['hours'])
            if hours < 1 or hours > 24:
                raise ValueError
        except (ValueError, KeyError):
            flash('Please enter a valid duration (1–24 hours)', 'danger')
            return redirect(url_for('book_slot', slot_id=slot_id))

        # Calculate cost and set up booking
        total_cost = slot.hourly_rate * hours
        booking = Booking(
            user_id=current_user.id,
            slot_id=slot.id,
            start_time=datetime.now(),
            booked_hours=hours,
            expected_end_time=datetime.now() + timedelta(hours=hours),
            total_cost=total_cost,
            status='active'
        )

        # Mark slot as booked
        slot.status = 'booked'

        # Persist to DB
        db.session.add(booking)
        db.session.commit()

        # Redirect to confirmation
        return redirect(url_for('booking_confirmation', booking_id=booking.id))

    # GET: render the booking modal HTML
    return render_template('booking_modal.html', slot=slot)

@app.route('/booking-confirmation/<int:booking_id>')
@login_required
def booking_confirmation(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template('booking_confirmation.html', booking=booking)

@app.route('/exit-booking/<int:booking_id>')
@login_required
def exit_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        abort(403)
    
    # Calculate actual duration
    actual_duration = (datetime.now() - booking.start_time).total_seconds() / 3600
    actual_cost = actual_duration * booking.slot.hourly_rate

    # Update booking
    booking.end_time = datetime.now()
    booking.total_cost = actual_cost
    booking.status = 'completed'
    
    # Free up parking slot
    booking.slot.status = 'available'
    
    db.session.commit()
    
    return redirect(url_for('payment', booking_id=booking.id))

@app.route('/payment/<int:booking_id>')
@login_required
def payment(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    return render_template('payment.html', booking=booking)


# @app.route('/admin')
# @admin_required
# def admin_dashboard():
#     # Key statistics
#     stats = {
#         'total_slots': ParkingSlot.query.count(),
#         'available_slots': ParkingSlot.query.filter_by(status='available').count(),
#         'active_bookings': Booking.query.filter_by(status='active').count(),
#         'total_users': User.query.count(),
#         'daily_revenue': db.session.query(db.func.sum(Booking.total_cost))
#                           .filter(Booking.end_time >= datetime.now() - timedelta(days=1))
#                           .scalar() or 0
#     }
    
#     # Recent activities
#     recent_bookings = Booking.query.order_by(Booking.start_time.desc()).limit(10).all()
    
#     return render_template('admin/dashboard.html', 
#                          stats=stats,
#                          recent_bookings=recent_bookings)

# @app.route('/admin')
# @admin_required
# def admin_dashboard():
#     # Determine which week offset to show (0 = current week, 1 = last week, etc.)
#     week_offset = request.args.get('week', 0, type=int)
#     # Compute start / end dates for that week (Mon – Sun)
#     today = datetime.now().date()
#     # find this week's Monday
#     this_monday = today - timedelta(days=today.weekday())
#     # shift by week_offset
#     start_date = this_monday - timedelta(weeks=week_offset)
#     end_date = start_date + timedelta(days=6)

#     # 1) Dynamic Revenue: sum per day over the week
#     daily_revenue = []
#     labels = []
#     for i in range(7):
#         day = start_date + timedelta(days=i)
#         next_day = day + timedelta(days=1)
#         revenue = db.session.query(db.func.coalesce(db.func.sum(Booking.total_cost), 0)) \
#             .filter(Booking.end_time >= datetime.combine(day, datetime.min.time()),
#                     Booking.end_time <  datetime.combine(next_day, datetime.min.time())) \
#             .scalar()
#         daily_revenue.append(float(revenue))
#         labels.append(day.strftime('%a'))

#     # 2) Stats as before
#     stats = {
#         'total_slots': ParkingSlot.query.count(),
#         'available_slots': ParkingSlot.query.filter_by(status='available').count(),
#         'active_bookings': Booking.query.filter_by(status='active').count(),
#         'total_users': User.query.count(),
#         'daily_revenue': sum(daily_revenue)  # total for the week
#     }

#     # 3) Paginated recent bookings
#     page = request.args.get('page', 1, type=int)
#     per_page = 10
#     recent_q = Booking.query.order_by(Booking.start_time.desc())
#     recent_page = recent_q.paginate(page=page, per_page=per_page, error_out=False)

#     return render_template('admin/dashboard.html',
#                            stats=stats,
#                            labels=labels,
#                            data=daily_revenue,
#                            week_offset=week_offset,
#                            recent_bookings=recent_page.items,
#                            pagination=recent_page)

@app.route('/admin')
@admin_required
def admin_dashboard():
    # Determine which week offset to show (0 = current week, 1 = last week, etc.)
    week_offset = request.args.get('week', 0, type=int)
    # Compute start / end dates for that week (Mon – Sun)
    today = datetime.now().date()
    # find this week's Monday
    this_monday = today - timedelta(days=today.weekday())
    # shift by week_offset
    start_date = this_monday - timedelta(weeks=week_offset)
    end_date = start_date + timedelta(days=6)

    # 1) Dynamic Revenue: sum per day over the week
    daily_revenue = []
    labels = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        next_day = day + timedelta(days=1)
        revenue = db.session.query(db.func.coalesce(db.func.sum(Booking.total_cost), 0)) \
            .filter(Booking.end_time >= datetime.combine(day, datetime.min.time()),
                    Booking.end_time <  datetime.combine(next_day, datetime.min.time())) \
            .scalar()
        daily_revenue.append(float(revenue))
        labels.append(day.strftime('%a'))

    # 2) Stats calculation - make sure available_slots is correctly calculated
    available_slots_count = ParkingSlot.query.filter_by(status='available').count()
    
    # Debug - print to console to verify
    print(f"Available slots count: {available_slots_count}")
    
    stats = {
        'total_slots': ParkingSlot.query.count(),
        'available_slots': available_slots_count,
        'active_bookings': Booking.query.filter_by(status='active').count(),
        'total_users': User.query.count(),
        'daily_revenue': sum(daily_revenue),  # total for the week
        # Add vehicle-specific counts for the modal
        'available_car_slots': ParkingSlot.query.filter_by(status='available', vehicle_type='car').count(),
        'available_bike_slots': ParkingSlot.query.filter_by(status='available', vehicle_type='bike').count(),
        'available_truck_slots': ParkingSlot.query.filter_by(status='available', vehicle_type='truck').count(),
    }

    # 3) Paginated recent bookings
    page = request.args.get('page', 1, type=int)
    per_page = 10
    recent_q = Booking.query.order_by(Booking.start_time.desc())
    recent_page = recent_q.paginate(page=page, per_page=per_page, error_out=False)

    return render_template('admin/dashboard.html',
                           stats=stats,
                           labels=labels,
                           data=daily_revenue,
                           week_offset=week_offset,
                           recent_bookings=recent_page.items,
                           pagination=recent_page)

@app.route('/admin/generate-report')
@admin_required
def generate_report():
    report_type = request.args.get('type', 'all')
    
    if report_type == 'bookings':
        data = {'bookings': Booking.query.order_by(Booking.start_time.desc()).all()}
        title = "Parking Bookings Report"
    elif report_type == 'revenue':
        revenue_data = db.session.query(
            db.func.date(Booking.end_time).label('date'),
            db.func.sum(Booking.total_cost).label('revenue')
        ).filter(Booking.end_time.isnot(None)).group_by('date').all()
        data = {'revenue': revenue_data}
        title = "Revenue Report"
    elif report_type == 'slots':
        data = {'slots': ParkingSlot.query.all()}
        title = "Parking Slots Report"
    else:  # 'all' case
        data = {
            'bookings': Booking.query.order_by(Booking.start_time.desc()).all(),
            'slots': ParkingSlot.query.all(),
            'revenue': db.session.query(
                db.func.date(Booking.end_time).label('date'),
                db.func.sum(Booking.total_cost).label('revenue')
            ).filter(Booking.end_time.isnot(None)).group_by('date').all()
        }
        title = "Complete Parking System Report"
    
    return render_template('admin/report_template.html',
                         data=data,
                         title=title,
                         report_type=report_type,
                         now=datetime.now())


@app.route('/admin/slots')
@admin_required
def manage_slots():
    slots = ParkingSlot.query.all()
    return render_template('admin/slots.html', slots=slots)

# @app.route('/admin/slots/<int:slot_id>', methods=['POST'])
# @admin_required
# def update_slot(slot_id):
#     slot = ParkingSlot.query.get_or_404(slot_id)
#     # grab the form values
#     status = request.form.get('status')
#     rate = request.form.get('hourly_rate')

#     # validate and apply
#     if status in ('available', 'booked'):
#         slot.status = status
#     else:
#         flash(f"Invalid status '{status}'", 'danger')

#     try:
#         slot.hourly_rate = float(rate)
#     except (ValueError, TypeError):
#         flash('Hourly rate must be a number', 'danger')

#     db.session.commit()
#     flash('Slot updated successfully', 'success')
#     return redirect(url_for('manage_slots'))

# @app.route('/admin/slots/<int:slot_id>', methods=['POST'])
# @admin_required
# def update_slot(slot_id):
#     slot = ParkingSlot.query.get_or_404(slot_id)
#     status = request.form.get('status')
#     rate = request.form.get('hourly_rate')
#     vehicle_type = request.form.get('vehicle_type')

#     if status in ('available', 'booked'):
#         slot.status = status
#     else:
#         flash(f"Invalid status '{status}'", 'danger')

#     try:
#         slot.hourly_rate = float(rate)
#     except (ValueError, TypeError):
#         flash('Hourly rate must be a number', 'danger')

#     if vehicle_type in ('car', 'bike', 'truck'):
#         slot.vehicle_type = vehicle_type
#     else:
#         flash('Invalid vehicle type', 'danger')

#     db.session.commit()
#     flash('Slot updated successfully', 'success')
#     return redirect(url_for('manage_slots'))

@app.route('/admin/slots/<int:slot_id>', methods=['POST'])
@admin_required
def update_slot(slot_id):
    slot = ParkingSlot.query.get_or_404(slot_id)
    status = request.form.get('status')
    rate = request.form.get('hourly_rate')
    vehicle_type = request.form.get('vehicle_type')

    if status in ('available', 'booked'):
        slot.status = status
    else:
        flash(f"Invalid status '{status}'", 'danger')

    try:
        slot.hourly_rate = float(rate)
    except (ValueError, TypeError):
        flash('Hourly rate must be a number', 'danger')

    if vehicle_type in ('car', 'bike', 'truck'):
        slot.vehicle_type = vehicle_type
    else:
        flash('Invalid vehicle type', 'danger')

    db.session.commit()
    flash('Slot updated successfully', 'success')
    return redirect(url_for('manage_slots'))

@app.route('/admin/users')
@admin_required
def manage_users():
    search_query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    
    users = User.query.filter(
        User.username.ilike(f'%{search_query}%')
    ).order_by(User.created_at.desc()).paginate(
        page=page, 
        per_page=10,
        error_out=False
    )
    
    return render_template('admin/users.html', 
                         users=users,
                         search_query=search_query)

@app.route('/admin/users/<int:user_id>/edit')
@admin_required
def get_user_data(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify({
        'id': user.id,
        'role': user.role,
        'vehicle_number': user.vehicle_number
    })

@app.route('/admin/users/<int:user_id>', methods=['PUT', 'DELETE'])
@admin_required
def manage_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'PUT':
        user.role = request.form.get('role', user.role)
        user.vehicle_number = request.form.get('vehicle_number', user.vehicle_number)
        db.session.commit()
        return jsonify({'message': 'User updated successfully'}), 200
        
    if request.method == 'DELETE':
        if user == current_user:
            return jsonify({'error': 'Cannot delete yourself'}), 403
        db.session.delete(user)
        db.session.commit()
        return jsonify({'message': 'User deleted successfully'}), 200


# --- Add Slot Route ---
@app.route('/admin/slots/add', methods=['POST'])
@admin_required
def add_slot():
    name = request.form.get('name', '').strip()
    rate = request.form.get('hourly_rate', '').strip()
    vehicle_type = request.form.get('vehicle_type', 'car')
    
    if not name or not rate:
        flash('Both name and rate are required', 'danger')
        return redirect(url_for('manage_slots'))

    try:
        hourly_rate = float(rate)
    except ValueError:
        flash('Hourly rate must be a number', 'danger')
        return redirect(url_for('manage_slots'))

    slot = ParkingSlot(name=name, hourly_rate=hourly_rate, vehicle_type=vehicle_type)
    db.session.add(slot)
    try:
        db.session.commit()
        flash(f"Slot '{name}' added.", 'success')
    except IntegrityError:
        db.session.rollback()
        flash(f"Slot name '{name}' is already in use.", 'danger')
    return redirect(url_for('manage_slots'))



# --- Delete Slot Route ---
@app.route('/admin/slots/<int:slot_id>/delete', methods=['POST'])
@admin_required
def delete_slot(slot_id):
    slot = ParkingSlot.query.get_or_404(slot_id)
    if slot.bookings:
        flash('Cannot delete a slot that has booking history.', 'danger')
    else:
        db.session.delete(slot)
        db.session.commit()
        flash(f"Slot '{slot.name}' deleted.", 'success')
    return redirect(url_for('manage_slots'))

with app.app_context():
    db.create_all()
if __name__ == '__main__':
    app.run(debug=True)