from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file, session, jsonify
from db import get_db_connection
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
import os
import logging
import csv
import tempfile
from functools import wraps

# Create a Blueprint for main application routes
main_bp = Blueprint('main', __name__)

# --- Ensure this decorator is present ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You need to be logged in to view this page.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

@main_bp.route('/')
def index():
    # This will direct any user visiting the root URL to the login page.
    return redirect(url_for('auth.login'))

# --- Existing API endpoint: get_subcategories ---
@main_bp.route('/api/get_subcategories/<int:category_id>')
def get_subcategories(category_id):
    conn = get_db_connection()
    subcategories = conn.execute('SELECT id, name FROM subcategories WHERE category_id = ? ORDER BY name', (category_id,)).fetchall()
    conn.close()
    return jsonify([dict(row) for row in subcategories])

# --- New: API endpoint used by front-end to get purchase categories ---
@main_bp.route('/api/get_purchase_categories')
def get_purchase_categories():
    conn = get_db_connection()
    rows = conn.execute('SELECT id, name FROM categories ORDER BY name').fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])

# --- New: API endpoint used by front-end to get purchase subcategories ---
@main_bp.route('/api/get_purchase_subcategories/<int:category_id>')
def get_purchase_subcategories(category_id):
    conn = get_db_connection()
    rows = conn.execute('SELECT id, name FROM subcategories WHERE category_id = ? ORDER BY name', (category_id,)).fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])

# --- New: API endpoint used by front-end to get specs for a subcategory ---
@main_bp.route('/api/get_purchase_specs/<int:subcategory_id>')
def get_purchase_specs(subcategory_id):
    """
    Returns items (id, specs) for the given subcategory_id that have meaningful specs.
    Filters out NULL, empty strings and '-' sentinel values.
    """
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT DISTINCT i.id as id, TRIM(i.specs) as specs
        FROM items i
        JOIN purchases p ON i.id = p.item_id
        WHERE i.subcategory_id = ?
          AND i.specs IS NOT NULL
          AND TRIM(i.specs) <> ''
          AND TRIM(i.specs) <> '-'
        ORDER BY i.specs
    """, (subcategory_id,)).fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "specs": r["specs"]} for r in rows])

# FIX: Add API endpoint to add a new category
@main_bp.route('/add_category', methods=['POST'])
def add_category():
    data = request.get_json()
    name = data.get('name', '').strip()

    if not name:
        return jsonify({'success': False, 'message': 'Category name cannot be empty.'}), 400

    conn = get_db_connection()
    try:
        existing = conn.execute('SELECT id FROM categories WHERE LOWER(name) = LOWER(?)', (name,)).fetchone()
        if existing:
            return jsonify({'success': False, 'message': 'Category already exists.'}), 409
        
        cursor = conn.execute('INSERT INTO categories (name) VALUES (?)', (name,))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'category_id': new_id})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

# FIX: Add API endpoint to add a new subcategory
@main_bp.route('/add_subcategory', methods=['POST'])
def add_subcategory():
    data = request.get_json()
    name = data.get('name', '').strip()
    category_id = data.get('category_id')

    if not name or not category_id:
        return jsonify({'success': False, 'message': 'Subcategory name and category ID are required.'}), 400

    conn = get_db_connection()
    try:
        existing = conn.execute('SELECT id FROM subcategories WHERE LOWER(name) = LOWER(?) AND category_id = ?', (name, category_id)).fetchone()
        if existing:
            return jsonify({'success': False, 'message': 'Subcategory already exists for this category.'}), 409

        cursor = conn.execute('INSERT INTO subcategories (name, category_id) VALUES (?, ?)', (name, category_id))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return jsonify({'success': True, 'subcategory_id': new_id})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500


@main_bp.route('/dashboard')
def dashboard():
    conn = get_db_connection()
    total_purchase_quantity = conn.execute('SELECT COALESCE(SUM(quantity), 0) as total_quantity FROM purchases').fetchone()['total_quantity']
    total_issue_quantity = conn.execute('SELECT COALESCE(SUM(CASE WHEN is_return = 0 THEN quantity ELSE 0 END), 0) as total_quantity FROM issues').fetchone()['total_quantity']
    total_staff_count = conn.execute('SELECT COUNT(*) as total_staff FROM staff').fetchone()['total_staff']
    stock_data = conn.execute('''
        WITH all_categories AS (SELECT DISTINCT c.name as category, s.name as subcategory FROM items i LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id WHERE c.name IS NOT NULL AND s.name IS NOT NULL),
        purchase_totals AS (SELECT c.name as category, s.name as subcategory, COALESCE(SUM(p.quantity), 0) as total_purchased FROM items i LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id LEFT JOIN purchases p ON i.id = p.item_id WHERE c.name IS NOT NULL AND s.name IS NOT NULL GROUP BY c.name, s.name),
        issue_totals AS (SELECT c.name as category, s.name as subcategory, COALESCE(SUM(CASE WHEN iss.is_return = 0 THEN iss.quantity ELSE 0 END), 0) as total_issued FROM items i LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id LEFT JOIN issues iss ON i.id = iss.item_id WHERE c.name IS NOT NULL AND s.name IS NOT NULL GROUP BY c.name, s.name)
        SELECT ac.category, ac.subcategory, COALESCE(pt.total_purchased, 0) as total_purchased, COALESCE(it.total_issued, 0) as total_issued, COALESCE(pt.total_purchased, 0) - COALESCE(it.total_issued, 0) as stock_available
        FROM all_categories ac LEFT JOIN purchase_totals pt ON ac.category = pt.category AND ac.subcategory = pt.subcategory LEFT JOIN issue_totals it ON ac.category = it.category AND ac.subcategory = it.subcategory ORDER BY ac.category, ac.subcategory
    ''').fetchall()
    conn.close()
    # FIX: Render the 'stock.html' template instead of 'dashboard.html'
    return render_template('stock.html', total_purchase_quantity=total_purchase_quantity, total_issue_quantity=total_issue_quantity, total_staff_count=total_staff_count, stock_data=stock_data)

@main_bp.route('/stock')
@login_required
def stock():
    conn = get_db_connection()
    total_purchase_quantity = conn.execute('SELECT COALESCE(SUM(quantity), 0) as total_quantity FROM purchases').fetchone()['total_quantity']
    total_issue_quantity = conn.execute('SELECT COALESCE(SUM(CASE WHEN is_return = 0 THEN quantity ELSE 0 END), 0) as total_quantity FROM issues').fetchone()['total_quantity']
    total_staff_count = conn.execute('SELECT COUNT(*) as total_staff FROM staff').fetchone()['total_staff']
    stock_data = conn.execute('''
        WITH all_categories AS (SELECT DISTINCT c.name as category, s.name as subcategory FROM items i LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id WHERE c.name IS NOT NULL AND s.name IS NOT NULL),
        purchase_totals AS (SELECT c.name as category, s.name as subcategory, COALESCE(SUM(p.quantity), 0) as total_purchased FROM items i LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id LEFT JOIN purchases p ON i.id = p.item_id WHERE c.name IS NOT NULL AND s.name IS NOT NULL GROUP BY c.name, s.name),
        issue_totals AS (SELECT c.name as category, s.name as subcategory, COALESCE(SUM(CASE WHEN iss.is_return = 0 THEN iss.quantity ELSE 0 END), 0) as total_issued FROM items i LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id LEFT JOIN issues iss ON i.id = iss.item_id WHERE c.name IS NOT NULL AND s.name IS NOT NULL GROUP BY c.name, s.name)
        SELECT ac.category, ac.subcategory, COALESCE(pt.total_purchased, 0) as total_purchased, COALESCE(it.total_issued, 0) as total_issued, COALESCE(pt.total_purchased, 0) - COALESCE(it.total_issued, 0) as stock_available
        FROM all_categories ac LEFT JOIN purchase_totals pt ON ac.category = pt.category AND ac.subcategory = pt.subcategory LEFT JOIN issue_totals it ON ac.category = it.category AND ac.subcategory = it.subcategory ORDER BY ac.category, ac.subcategory
    ''').fetchall()
    conn.close()
    return render_template('stock.html', total_purchase_quantity=total_purchase_quantity, total_issue_quantity=total_issue_quantity, total_staff_count=total_staff_count, stock_data=stock_data)

@main_bp.route('/staff', methods=['GET', 'POST'])
def staff():
    conn = get_db_connection()
    if request.method == 'POST':
        dept = request.form['dept']
        if dept == 'Other':
            dept = request.form.get('custom_dept', '').strip()
        name = request.form['name']
        designation = request.form['designation']
        date_of_joining = request.form.get('date_of_joining', '').strip()
        if not date_of_joining:
            date_of_joining = None
        if dept and name and designation:
            conn.execute('INSERT INTO staff (dept, name, designation, date_of_joining) VALUES (?, ?, ?, ?)', (dept, name, designation, date_of_joining))
            conn.commit()
            flash('Staff member added successfully!', 'success')
        else:
            flash('Department, Name, and Designation are required!', 'error')
        return redirect(url_for('main.staff'))
    staff_list = conn.execute('SELECT * FROM staff ORDER BY id DESC').fetchall()
    departments_raw = conn.execute('SELECT DISTINCT dept FROM staff ORDER BY dept').fetchall()
    departments = [d['dept'] for d in departments_raw]
    conn.close()
    return render_template('staff.html', staff=staff_list, departments=departments, title="Staff")

@main_bp.route('/staff/edit', methods=['POST'])
@login_required
def edit_staff():
    staff_id = request.form['id']
    name = request.form['name']
    designation = request.form['designation']
    date_of_joining = request.form.get('date_of_joining', '').strip()
    dept = request.form.get('dept', '').strip()   # <-- added

    if not date_of_joining:
        date_of_joining = None

    conn = get_db_connection()
    conn.execute(
        'UPDATE staff SET name = ?, designation = ?, date_of_joining = ?, dept = ? WHERE id = ?',
        (name, designation, date_of_joining, dept, staff_id)
    )
    conn.commit()
    conn.close()
    flash('Staff updated successfully!', 'success')
    return redirect(url_for('main.staff'))


@main_bp.route('/staff/delete/<int:staff_id>', methods=['POST', 'GET'])
@login_required
def delete_staff(staff_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM staff WHERE id = ?', (staff_id,))
    conn.commit()
    conn.close()
    flash('Staff deleted successfully!', 'success')
    return redirect(url_for('main.staff'))

@main_bp.route('/items', methods=['GET', 'POST'])
def items():
    conn = get_db_connection()
    if request.method == 'POST':
        category_id = request.form['category_id']
        custom_category = request.form.get('custom_category', '').strip()
        subcategory_id = request.form['subcategory_id']
        custom_subcategory = request.form.get('custom_subcategory', '').strip()
        remarks = request.form.get('remarks', '').strip()
        if category_id == 'custom' and custom_category:
            existing = conn.execute('SELECT id FROM categories WHERE LOWER(name) = LOWER(?)', (custom_category,)).fetchone()
            if existing:
                category_id = existing['id']
            else:
                conn.execute('INSERT INTO categories (name) VALUES (?)', (custom_category,))
                conn.commit()
                category_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        if subcategory_id == 'custom' and custom_subcategory:
            existing = conn.execute('SELECT id FROM subcategories WHERE LOWER(name) = LOWER(?) AND category_id = ?', (custom_subcategory, category_id)).fetchone()
            if existing:
                subcategory_id = existing['id']
            else:
                conn.execute('INSERT INTO subcategories (name, category_id) VALUES (?, ?)', (custom_subcategory, category_id))
                conn.commit()
                subcategory_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        
        if category_id and subcategory_id:
            conn.execute('INSERT INTO items (category_id, subcategory_id, specs) VALUES (?, ?, ?)', (category_id, subcategory_id, remarks))
            conn.commit()
            flash('Item added successfully!', 'success')
        else:
            flash('Category and Subcategory are required!', 'error')
        
        # FIX: Redirect after the POST request is processed
        conn.close()
        return redirect(url_for('main.items'))

    # This part now only runs for GET requests
    categories = conn.execute('SELECT MIN(id) as id, name FROM categories GROUP BY LOWER(name) ORDER BY name ASC').fetchall()
    items = conn.execute('SELECT i.id, c.name as category, s.name as subcategory, i.specs as remarks FROM items i LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id ORDER BY i.id DESC').fetchall()
    conn.close()
    return render_template('items.html', categories=categories, items=items)

@main_bp.route('/purchase', methods=['GET', 'POST'])
@login_required
def purchase():
    conn = get_db_connection()
    if request.method == 'POST':
        vendor = request.form.get('vendor')
        purchase_date = request.form.get('purchase_date')
        
        filename = None
        if 'bill_image' in request.files:
            file = request.files['bill_image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                upload_folder = os.path.join(current_app.root_path, 'static', 'uploads')
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                file.save(os.path.join(upload_folder, filename))

        try:
            category_ids = request.form.getlist('category_id[]')
            subcategory_ids = request.form.getlist('subcategory_id[]')
            serial_nos = request.form.getlist('serial_no[]')
            quantities = request.form.getlist('quantity[]')
            unit_prices = request.form.getlist('unit_price[]')
            remarks_list = request.form.getlist('item_remarks[]')
            specs_list = request.form.getlist('specs[]')

            for i in range(len(category_ids)):
                category_id = category_ids[i]
                subcategory_id = subcategory_ids[i]
                
                if not category_id or not subcategory_id:
                    continue

                # FIX: Use the specs from the current form row
                item_specs = specs_list[i] if i < len(specs_list) else ''

                item_id_row = conn.execute('SELECT id FROM items WHERE category_id = ? AND subcategory_id = ? AND specs = ?', 
                                           (category_id, subcategory_id, item_specs)).fetchone()
                
                if item_id_row:
                    item_id = item_id_row['id']
                else:
                    cursor = conn.execute('INSERT INTO items (category_id, subcategory_id, specs) VALUES (?, ?, ?)', 
                                          (category_id, subcategory_id, item_specs))
                    conn.commit()
                    item_id = cursor.lastrowid

                serial_no = serial_nos[i]
                quantity = quantities[i]
                unit_price = unit_prices[i]
                remarks = remarks_list[i]

                quantity = int(quantity) if quantity else 0
                unit_price = float(unit_price) if unit_price else 0.0

                if item_id and quantity > 0:
                    # FIX: Add bill_image to the INSERT statement
                    conn.execute("""
                        INSERT INTO purchases (item_id, vendor, date, serial_no, quantity, unit_price, remarks, bill_image)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (item_id, vendor, purchase_date, serial_no, quantity, unit_price, remarks, filename))
            
            conn.commit()
            flash('Purchase recorded successfully!', 'success')
        except IndexError:
            conn.rollback()
            flash('An error occurred: Form data was incomplete. Please try again.', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'An error occurred: {e}', 'danger')
        finally:
            conn.close()
        
        return redirect(url_for('main.purchase'))

    # GET request logic
    search = request.args.get('search', '')
    query_params = []
    sql_query = """
        SELECT 
            p.id, p.vendor, p.date, c.name as category, s.name as subcategory, 
            i.specs,p.remarks, p.serial_no, p.quantity, p.unit_price, 
            (p.quantity * p.unit_price) as total_price, p.bill_image
        FROM purchases p
        JOIN items i ON p.item_id = i.id
        JOIN categories c ON i.category_id = c.id
        JOIN subcategories s ON i.subcategory_id = s.id
    """
    if search:
        sql_query += " WHERE p.vendor LIKE ? OR c.name LIKE ? OR s.name LIKE ? OR p.serial_no LIKE ?"
        query_params.extend([f'%{search}%'] * 4)
    
    sql_query += " ORDER BY p.id DESC"
    
    purchases = conn.execute(sql_query, query_params).fetchall()
    
    categories_rows = conn.execute('SELECT id, name FROM categories ORDER BY name ASC').fetchall()
    categories = [dict(row) for row in categories_rows]

    # FIX: Add this logic to the GET request part as well
    subcategories_rows = conn.execute('SELECT id, name, category_id FROM subcategories').fetchall()
    subcategories_json = [dict(row) for row in subcategories_rows]
    
    conn.close()
    # FIX: Pass subcategories_json to the template
    return render_template('purchase.html', purchases=purchases, categories=categories, search=search, subcategories_json=subcategories_json)
@main_bp.route('/issue', methods=['GET', 'POST'])
def issue():
    conn = get_db_connection()
    if request.method == 'POST':
        try:
            department = request.form.get('department', '').strip()
            staff_name = request.form.get('staff_name', '').strip()
            specs_value = request.form.get('specs', '').strip()  # may be '' or item id
            quantity = int(request.form.get('quantity', 0))
            date = request.form.get('date', '').strip()
            remarks = request.form.get('remarks', '').strip()
            serial_no = request.form.get('serial_no', '').strip()  # <-- Add this line

            category_id = request.form.get('category', '').strip()
            subcategory_id = request.form.get('subcategory', '').strip()

            # Basic validation
            if not department or not staff_name or not category_id or not subcategory_id or not date or quantity == 0:
                flash('Department, Staff, Category, Subcategory, Date are required and quantity cannot be zero!', 'error')
                return redirect(url_for('main.issue'))

            # Check if this subcategory requires specs
            has_specs_row = conn.execute("""
                SELECT COUNT(DISTINCT i.id) as cnt
                FROM items i
                JOIN purchases p ON i.id = p.item_id
                WHERE i.category_id = ? AND i.subcategory_id = ?
                  AND i.specs IS NOT NULL
                  AND TRIM(i.specs) <> ''
                  AND TRIM(i.specs) <> '-'
            """, (category_id, subcategory_id)).fetchone()
            has_specs = bool(has_specs_row and has_specs_row['cnt'] > 0)

            item_id = None
            item_data = None

            if has_specs:
                # specs required
                if not specs_value:
                    flash('Specs selection is required for this item!', 'error')
                    return redirect(url_for('main.issue'))
                item_row = conn.execute("""
                    SELECT i.id, i.specs, c.name as category_name, s.name as subcategory_name
                    FROM items i
                    LEFT JOIN categories c ON i.category_id = c.id
                    LEFT JOIN subcategories s ON i.subcategory_id = s.id
                    WHERE i.id = ?
                """, (specs_value,)).fetchone()
                if not item_row:
                    flash('Invalid item selected!', 'error')
                    return redirect(url_for('main.issue'))
                item_id = item_row['id']
                item_data = item_row
            else:
                # no specs needed
                item_row = conn.execute("""
                    SELECT i.id, i.specs, c.name as category_name, s.name as subcategory_name
                    FROM items i
                    LEFT JOIN categories c ON i.category_id = c.id
                    LEFT JOIN subcategories s ON i.subcategory_id = s.id
                    WHERE i.category_id = ? AND i.subcategory_id = ?
                    ORDER BY 
                      CASE WHEN i.specs IS NULL THEN 0 
                           WHEN TRIM(i.specs) = '' THEN 1 
                           WHEN TRIM(i.specs) = '-' THEN 2 
                           ELSE 3 END,
                      i.id
                    LIMIT 1
                """, (category_id, subcategory_id)).fetchone()

                if item_row:
                    item_id = item_row['id']
                    item_data = item_row
                else:
                    # create new item with no specs
                    cursor = conn.execute(
                        'INSERT INTO items (category_id, subcategory_id, specs) VALUES (?, ?, ?)',
                        (category_id, subcategory_id, None)
                    )
                    conn.commit()
                    item_id = cursor.lastrowid
                    cat_row = conn.execute('SELECT name FROM categories WHERE id = ?', (category_id,)).fetchone()
                    sub_row = conn.execute('SELECT name FROM subcategories WHERE id = ?', (subcategory_id,)).fetchone()
                    item_data = {
                        'id': item_id,
                        'specs': None,
                        'category_name': cat_row['name'] if cat_row else None,
                        'subcategory_name': sub_row['name'] if sub_row else None
                    }

            if not item_id:
                flash('Could not determine item to issue.', 'error')
                return redirect(url_for('main.issue'))

            # stock check
            if quantity > 0:
                total_purchased = conn.execute(
                    'SELECT COALESCE(SUM(quantity), 0) as total_purchased FROM purchases WHERE item_id = ?',
                    (item_id,)
                ).fetchone()['total_purchased']
                total_issued = conn.execute(
                    'SELECT COALESCE(SUM(CASE WHEN is_return = 0 THEN quantity ELSE 0 END), 0) as total_issued FROM issues WHERE item_id = ?',
                    (item_id,)
                ).fetchone()['total_issued']
                available_stock = total_purchased - total_issued
                if quantity > available_stock:
                    flash(f'Insufficient stock! Available: {available_stock}, Requested: {quantity}', 'error')
                    return redirect(url_for('main.issue'))

                # FIX: Check serial number stock if provided
                if serial_no:
                    total_purchased_serial = conn.execute(
                        'SELECT COALESCE(SUM(quantity), 0) as total_purchased FROM purchases WHERE item_id = ? AND serial_no = ?',
                        (item_id, serial_no)
                    ).fetchone()['total_purchased']
                    total_issued_serial = conn.execute(
                        'SELECT COALESCE(SUM(CASE WHEN is_return = 0 THEN quantity ELSE 0 END), 0) as total_issued FROM issues WHERE item_id = ? AND serial_no = ?',
                        (item_id, serial_no)
                    ).fetchone()['total_issued']
                    available_serial_stock = total_purchased_serial - total_issued_serial
                    if quantity > available_serial_stock:
                        flash(f'Serial No {serial_no} has insufficient stock! Available: {available_serial_stock}, Requested: {quantity}', 'error')
                        conn.close()
                        return redirect(url_for('main.issue'))

            # returns
            if quantity < 0:
                positive_qty = abs(quantity)
                original_issue = conn.execute(
                    'SELECT id FROM issues WHERE department = ? AND staff_name = ? AND item_id = ? AND quantity = ? AND is_return = 0 ORDER BY id DESC LIMIT 1',
                    (department, staff_name, item_id, positive_qty)
                ).fetchone()
                if original_issue:
                    conn.execute(
                        'UPDATE issues SET is_return = 1, return_reason = ?, return_date = ? WHERE id = ?',
                        (remarks or f"Returned on {date}", date, original_issue['id'])
                    )
                else:
                    flash('No matching issue found to return!', 'error')
                    return redirect(url_for('main.issue'))
            else:
                # issue new item
                specs_val = None
                cat_val = None
                sub_val = None

                # sqlite3.Row behaves like dict, no .get()
                if isinstance(item_data, dict):
                    specs_val = item_data.get('specs')
                    cat_val = item_data.get('category_name')
                    sub_val = item_data.get('subcategory_name')
                else:
                    specs_val = item_data['specs'] if 'specs' in item_data.keys() else None
                    cat_val = item_data['category_name'] if 'category_name' in item_data.keys() else None
                    sub_val = item_data['subcategory_name'] if 'subcategory_name' in item_data.keys() else None

                item_name = specs_val or sub_val or cat_val or ""

                conn.execute(
                    'INSERT INTO issues (dept_id, item_id, quantity, date, specs, remarks, department, staff_name, item_name, category, subcategory, is_return, serial_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (None, item_id, quantity, date, specs_val, remarks, department, staff_name, item_name, cat_val, sub_val, 0, serial_no)
                )

            conn.commit()
            if quantity < 0:
                flash('Item returned successfully!', 'success')
            else:
                flash('Item issued successfully!', 'success')

        except Exception as e:
            conn.rollback()
            logging.error(f"Error processing issue: {e}")
            flash(f'Error processing issue: {str(e)}', 'error')
        return redirect(url_for('main.issue'))

    # GET: show issues
    issues = conn.execute("""
        SELECT iss.id, iss.department, iss.staff_name, iss.item_name, iss.specs, 
               iss.quantity, iss.date, iss.remarks, iss.is_return, 
               iss.return_reason, iss.return_date, iss.serial_no, 
               c.name as category_name, s.name as subcategory_name
        FROM issues iss
        LEFT JOIN items i ON iss.item_id = i.id
        LEFT JOIN categories c ON i.category_id = c.id
        LEFT JOIN subcategories s ON i.subcategory_id = s.id
        ORDER BY iss.id DESC
    """).fetchall()
    conn.close()
    return render_template('issue.html', issues=issues)

@main_bp.route('/download')
def download():
    conn = get_db_connection()
    bills = conn.execute('''SELECT b.id, b.vendor, b.date, b.remarks, b.bill_image, GROUP_CONCAT(p.quantity || ' x ' || c.name || ' (' || s.name || ')') as items FROM bills b LEFT JOIN purchases p ON b.id = p.bill_id LEFT JOIN items i ON p.item_id = i.id LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id GROUP BY b.id, b.vendor, b.date, b.remarks, b.bill_image ORDER BY b.id DESC''').fetchall()
    conn.close()
    return render_template('download.html', bills=bills)

@main_bp.route('/download_purchases')
def download_purchases():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    conn = get_db_connection()
    query = 'SELECT p.id, p.vendor, p.date, c.name as category, s.name as subcategory, i.specs, p.serial_no, p.quantity, p.unit_price, (p.quantity * p.unit_price) as total_price FROM purchases p LEFT JOIN items i ON p.item_id = i.id LEFT JOIN categories c ON i.category_id = c.id LEFT JOIN subcategories s ON i.subcategory_id = s.id'
    params = []
    if start_date and end_date:
        query += ' WHERE date(substr(p.date, 7, 4) || \'-\' || substr(p.date, 4, 2) || \'-\' || substr(p.date, 1, 2)) BETWEEN date(?) AND date(?)'
        params = [start_date, end_date]
    query += ' ORDER BY p.date DESC'
    purchases = conn.execute(query, params).fetchall()
    conn.close()
    temp = tempfile.NamedTemporaryFile(delete=False, mode='w', newline='', encoding='utf-8')
    writer = csv.writer(temp)
    writer.writerow(['Purchase ID', 'Vendor', 'Date', 'Category', 'Subcategory', 'Specifications', 'Serial Number', 'Quantity', 'Unit Price', 'Total Price'])
    total_items = 0
    total_amount = 0.0
    for p in purchases:
        writer.writerow([p['id'], p['vendor'], p['date'], p['category'], p['subcategory'], p['specs'] or '', p['serial_no'] or '', p['quantity'], f"{p['unit_price']:.2f}", f"{p['total_price']:.2f}"])
        total_items += p['quantity']
        total_amount += p['total_price']
    writer.writerow([])
    writer.writerow(['Total Items Purchased', total_items])
    writer.writerow(['Total Amount Purchased', f"{total_amount:.2f}"])
    temp.close()
    return send_file(temp.name, mimetype='text/csv', as_attachment=True, download_name=f'purchases_{start_date}_{end_date}.csv')
@main_bp.route('/laptop_report')
def laptop_report():
    filter_by = request.args.get('filter_by', 'All')
    filter_value = request.args.get('filter_value', '').strip()
    filter_date = request.args.get('filter_date', '').strip()

    conn = get_db_connection()
    params = []

    query = '''
        SELECT DISTINCT
            iss.staff_name AS Users,
            iss.department AS Department,
            iss.date AS "Issue Date",
            iss.specs AS Specs,
            p.date AS "Date of Purchase",
            iss.serial_no AS "Serial No",  -- <-- Changed here
            st.date_of_joining AS "Employee Joining Date",
            p.remarks AS "Description/Remarks"
        FROM issues iss
        LEFT JOIN items i ON iss.item_id = i.id
        LEFT JOIN purchases p ON i.id = p.item_id
        LEFT JOIN staff st ON iss.staff_name = st.name
        LEFT JOIN categories c ON i.category_id = c.id
        LEFT JOIN subcategories s ON i.subcategory_id = s.id
        WHERE LOWER(c.name) LIKE "%pc%"
          AND LOWER(s.name) = "laptop"
          AND (iss.is_return IS NULL OR iss.is_return = 0)
    '''

    if filter_by != 'All':
        if filter_by in ['Users', 'Department', 'Specs', 'Serial No'] and filter_value:
            filter_map = {
                'Users': 'iss.staff_name',
                'Department': 'iss.department',
                'Specs': 'iss.specs',
                'Serial No': 'iss.serial_no'  # <-- Changed here
            }
            query += f" AND {filter_map[filter_by]} LIKE ?"
            params.append(f'%{filter_value}%')
        elif filter_by in ['Date of Purchase', 'Issue Date', 'Employee Joining Date'] and filter_date:
            date_map = {
                'Date of Purchase': 'p.date',
                'Issue Date': 'iss.date',
                'Employee Joining Date': 'st.date_of_joining'
            }
            query += f" AND DATE({date_map[filter_by]}) = DATE(?)"
            params.append(filter_date)

    query += " GROUP BY iss.id ORDER BY iss.id DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    # --- Helpers ---
    def parse_date(s):
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    laptop_data = []
    for row in rows:
        purchase_str = row["Date of Purchase"]
        join_str = row["Employee Joining Date"]

        purchase_dt = parse_date(purchase_str)
        join_dt = parse_date(join_str)

        end_of_life_str = (purchase_dt + timedelta(days=1642)).strftime("%d %B, %Y") if purchase_dt else None
        eligibility_str = (join_dt + timedelta(days=547)).strftime("%d %B, %Y") if join_dt else None

        laptop_data.append({
            "Users": row["Users"],
            "Department": row["Department"],
            "Laptop Age Policy": "4.5 Years",
            "Date of Purchase": purchase_str,
            "End of Laptop Life": end_of_life_str,
            "Issue Date": row["Issue Date"],
            "Employee Joining Date": join_str,
            "Employee Eligibility": eligibility_str,
            "Specs": row["Specs"],
            "Serial No": row["Serial No"],
            "Description": row["Description/Remarks"]
        })

    return render_template('laptop_report.html', laptop_data=laptop_data, filter_by=filter_by)

@main_bp.route('/account/settings', methods=['GET', 'POST'])
def account_settings():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        user_id = session.get('user_id')

        if not all([current_password, new_password, confirm_password, user_id]):
            flash('All password fields are required.', 'error')
            return redirect(url_for('main.account_settings'))

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        
        if not user or not check_password_hash(user['password'], current_password):
            conn.close()
            flash('Your current password is not correct.', 'error')
            return redirect(url_for('main.account_settings'))

        if new_password != confirm_password:
            conn.close()
            flash('New passwords do not match.', 'error')
            return redirect(url_for('main.account_settings'))

        # Hash the new password and update the database
        hashed_password = generate_password_hash(new_password)
        conn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_password, user_id))
        conn.commit()
        conn.close()

        flash('Your password has been updated successfully.', 'success')
        return redirect(url_for('main.account_settings'))

    return render_template('account_settings.html')

from flask import request, jsonify

@main_bp.route('/get_serials')
def get_serials():
    specs_id = request.args.get('specs_id')
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT p.serial_no FROM purchases p
           JOIN items i ON p.item_id = i.id
           WHERE i.id = ? AND p.serial_no IS NOT NULL AND TRIM(p.serial_no) <> '' ''',
        (specs_id,)
    ).fetchall()
    conn.close()
    return jsonify([{"serial_no": r["serial_no"]} for r in rows])


@main_bp.route('/manage_users')
@login_required
def manage_users():
    # Only allow admins to access this page
    if session.get('role') != 'admin':
        flash("Access denied: Admins only.", "error")
        return redirect(url_for('main.dashboard'))
    conn = get_db_connection()
    users = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("manage_users.html", users=users, title="Manage Users")

@main_bp.route('/add_user', methods=['POST'])
@login_required
def add_user():
    # Only allow admins to add users
    if session.get('role') != 'admin':
        flash("Access denied: Admins only.", "error")
        return redirect(url_for('main.manage_users'))

    username = request.form['username']
    password = request.form['password']
    confirm_password = request.form['confirm_password']
    role = request.form['role']  # Get role from form

    if password != confirm_password:
        flash("Passwords do not match!", "error")
        return redirect(url_for('main.manage_users'))

    hashed_password = generate_password_hash(password)

    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hashed_password, role))
        conn.commit()
        flash("User added successfully!", "success")
    except Exception as e:
        flash("Error: Username may already exist", "error")
    finally:
        conn.close()

    return redirect(url_for('main.manage_users'))

@main_bp.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("User deleted successfully!", "success")
    return redirect(url_for('main.manage_users'))

@main_bp.route('/get_serials_by_subcategory')
def get_serials_by_subcategory():
    subcategory_id = request.args.get('subcategory_id')
    conn = get_db_connection()
    rows = conn.execute(
        '''SELECT p.serial_no FROM purchases p
           JOIN items i ON p.item_id = i.id
           WHERE i.subcategory_id = ? AND p.serial_no IS NOT NULL AND TRIM(p.serial_no) <> '' ''',
        (subcategory_id,)
    ).fetchall()
    conn.close()
    return jsonify([{"serial_no": r["serial_no"]} for r in rows])
