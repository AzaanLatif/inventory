from flask import Blueprint, jsonify, request
from db import get_db_connection
import logging

# Create a Blueprint for API routes, with a URL prefix
api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/get_subcategories/<int:category_id>')
def get_subcategories(category_id):
    conn = get_db_connection()
    subcategories = conn.execute('SELECT DISTINCT s.id, s.name FROM subcategories s WHERE s.category_id = ? ORDER BY s.name', (category_id,)).fetchall()
    conn.close()
    return jsonify([{'id': sub['id'], 'name': sub['name']} for sub in subcategories])

@api_bp.route('/add_category', methods=['POST'])
def add_category():
    try:
        data = request.get_json()
        category_name = data.get('name', '').strip()
        if not category_name:
            return jsonify({'success': False, 'message': 'Category name is required'})
        conn = get_db_connection()
        existing = conn.execute("SELECT id FROM categories WHERE LOWER(name) = LOWER(?)", (category_name,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'message': 'Category already exists'})
        conn.execute("INSERT INTO categories (name) VALUES (?)", (category_name,))
        category_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'category_id': category_id, 'message': 'Category added successfully'})
    except Exception as e:
        logging.error(f"Error adding category: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'})

@api_bp.route('/add_subcategory', methods=['POST'])
def add_subcategory():
    try:
        data = request.get_json()
        subcategory_name = data.get('name', '').strip()
        category_id = data.get('category_id')
        if not subcategory_name or not category_id:
            return jsonify({'success': False, 'message': 'Subcategory name and category are required'})
        conn = get_db_connection()
        existing = conn.execute("SELECT id FROM subcategories WHERE LOWER(name) = LOWER(?) AND category_id = ?", (subcategory_name, category_id)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'message': 'Subcategory already exists in this category'})
        conn.execute("INSERT INTO subcategories (name, category_id) VALUES (?, ?)", (subcategory_name, category_id))
        subcategory_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'subcategory_id': subcategory_id, 'message': 'Subcategory added successfully'})
    except Exception as e:
        logging.error(f"Error adding subcategory: {e}")
        return jsonify({'success': False, 'message': 'Internal server error'})

@api_bp.route('/get_staff_by_department/<department>')
def get_staff_by_department(department):
    try:
        conn = get_db_connection()
        staff = conn.execute('SELECT DISTINCT name, designation FROM staff WHERE LOWER(dept) = LOWER(?) ORDER BY name', (department,)).fetchall()
        conn.close()
        return jsonify([{'name': s['name'], 'designation': s['designation']} for s in staff])
    except Exception as e:
        logging.error(f"Error fetching staff: {e}")
        return jsonify([]), 500

@api_bp.route('/get_departments')
def get_departments():
    try:
        conn = get_db_connection()
        departments = conn.execute('SELECT DISTINCT dept FROM staff ORDER BY dept').fetchall()
        conn.close()
        return jsonify([dept['dept'] for dept in departments])
    except Exception as e:
        logging.error(f"Error fetching departments: {e}")
        return jsonify([]), 500

@api_bp.route('/get_purchase_categories')
def get_purchase_categories():
    try:
        conn = get_db_connection()
        categories = conn.execute('SELECT DISTINCT c.id, c.name FROM categories c LEFT JOIN items i ON c.id = i.category_id LEFT JOIN purchases p ON i.id = p.item_id ORDER BY c.name').fetchall()
        conn.close()
        return jsonify([{'id': cat['id'], 'name': cat['name']} for cat in categories])
    except Exception as e:
        logging.error(f"Error fetching purchase categories: {e}")
        return jsonify([]), 500

@api_bp.route('/get_purchase_subcategories/<int:category_id>')
def get_purchase_subcategories(category_id):
    try:
        conn = get_db_connection()
        subcategories = conn.execute('SELECT DISTINCT s.id, s.name FROM subcategories s LEFT JOIN items i ON s.id = i.subcategory_id LEFT JOIN purchases p ON i.id = p.item_id WHERE i.category_id = ? ORDER BY s.name', (category_id,)).fetchall()
        conn.close()
        return jsonify([{'id': sub['id'], 'name': sub['name']} for sub in subcategories])
    except Exception as e:
        logging.error(f"Error fetching purchase subcategories: {e}")
        return jsonify([]), 500

@api_bp.route('/get_purchase_specs/<int:subcategory_id>')
def get_purchase_specs(subcategory_id):
    try:
        conn = get_db_connection()
        specs = conn.execute('SELECT DISTINCT i.id, i.specs FROM items i INNER JOIN purchases p ON i.id = p.item_id WHERE i.subcategory_id = ? ORDER BY i.specs', (subcategory_id,)).fetchall()
        conn.close()
        return jsonify([{'id': spec['id'], 'specs': spec['specs']} for spec in specs])
    except Exception as e:
        logging.error(f"Error fetching purchase specs: {e}")
        return jsonify([]), 500