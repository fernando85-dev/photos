import sqlite3
import os
import datetime
import uuid
import zipfile
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from werkzeug.utils import secure_filename
import docx

# --- Constants ---
BASE_APP_DIR = os.path.dirname(os.path.abspath(__file__)) # Points to 'app' directory
PROJECT_ROOT_DIR = os.path.dirname(BASE_APP_DIR) # Points to project root

DATABASE_FILE = os.path.join(BASE_APP_DIR, 'database.db')
UPLOADS_DIR = os.path.join(PROJECT_ROOT_DIR, 'uploads')
TEMP_ZIP_DIR = os.path.join(BASE_APP_DIR, 'tmp_zip_files')

# --- Flask App Initialization ---
app = Flask(__name__)
app.secret_key = "supersecretkey" # Needed for flash messages
app.config['UPLOAD_FOLDER'] = UPLOADS_DIR
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'docx'}

# --- Global Settings ---
CURRENT_THEME = 'white'  # Default theme for the application
ALLOWED_THEMES = ['white', 'black', 'blue', 'green']  # List of valid theme names

# --- Theme Management Functions ---
def set_color_theme(theme_name: str) -> bool:
    """
    Sets the global color theme for the application.

    Args:
        theme_name: The name of the theme to set. Must be one of ALLOWED_THEMES.

    Returns:
        True if the theme was successfully set, False otherwise.
    """
    global CURRENT_THEME
    if theme_name in ALLOWED_THEMES:
        CURRENT_THEME = theme_name
        return True
    return False

def get_color_theme() -> str:
    return CURRENT_THEME

# --- Database Initialization ---
def init_db():
    """
    Initializes the database by creating necessary tables if they don't already exist.
    Also ensures that the upload and temporary zip directories are created.
    This function is typically called once at application startup.
    """
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(TEMP_ZIP_DIR, exist_ok=True)
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS albums (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                creation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                album_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                notes TEXT,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (album_id) REFERENCES albums (id)
            )
        """)
        conn.commit()
        print("Database initialized successfully.")
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")
    finally:
        if conn:
            conn.close()

# --- Database Connection Helper ---
def get_db_connection():
    """
    Establishes a connection to the SQLite database.

    Returns:
        A sqlite3.Connection object with row_factory set to sqlite3.Row
        to allow dictionary-like access to columns.
    """
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# --- Album Functions (Database Interactions) ---
def create_album(name: str) -> int | None:
    """
    Creates a new album in the database.

    Args:
        name: The desired name for the new album.

    Returns:
        The ID of the newly created album, or None if creation failed.
    """
    # (Code from previous steps, ensure it's robust)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO albums (name) VALUES (?)", (name,))
        conn.commit()
        new_album_id = cursor.lastrowid
        return new_album_id
    except sqlite3.Error as e:
        print(f"Error creating album: {e}")
        flash(f"Error creating album: {e}", "error")
        return None
    finally:
        if conn:
            conn.close()

def get_album_by_id(album_id: int) -> sqlite3.Row | None:
    """
    Retrieves a specific album from the database by its ID.

    Args:
        album_id: The ID of the album to retrieve.

    Returns:
        A sqlite3.Row object representing the album, or None if not found or error.
    """
    # (Code from previous steps)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM albums WHERE id = ?", (album_id,))
        album = cursor.fetchone()
        return album
    except sqlite3.Error as e:
        print(f"Error fetching album by ID: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_all_albums() -> list[sqlite3.Row]:
    """
    Retrieves all albums from the database, ordered by creation date (descending).

    Returns:
        A list of sqlite3.Row objects, each representing an album.
        Returns an empty list if no albums are found or an error occurs.
    """
    # (Code from previous steps)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM albums ORDER BY creation_date DESC")
        albums = cursor.fetchall()
        return albums
    except sqlite3.Error as e:
        print(f"Error fetching all albums: {e}")
        return []
    finally:
        if conn:
            conn.close()

# --- Photo Functions (Database and File Interactions) ---
def allowed_file(filename: str) -> bool:
    """
    Checks if a given filename has an allowed extension.

    Args:
        filename: The name of the file to check.

    Returns:
        True if the file extension is in the ALLOWED_EXTENSIONS set, False otherwise.
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def upload_photo(album_id: int, photo_file_storage, notes: str = "") -> int | None:
    """
    Handles the uploading of a photo. This includes:
    - Securing the filename.
    - Checking if the file type is allowed.
    - Saving the photo file to the UPLOAD_FOLDER with a unique name.
    - Storing photo metadata (album_id, unique filename, notes) in the database.

    Args:
        album_id: The ID of the album to which the photo belongs.
        photo_file_storage: The FileStorage object from Flask (request.files['photo']).
        notes: Optional notes or description for the photo.

    Returns:
        The ID of the newly uploaded photo record in the database, or None if upload failed.
    """
    if not photo_file_storage or not photo_file_storage.filename:
        flash("No file selected for upload.", "error")
        return None

    # Secure the filename before using it
    s_filename = secure_filename(photo_file_storage.filename)

    if not s_filename or not allowed_file(s_filename): # Check if filename became empty or type is disallowed
        flash(f"Invalid filename or file type not allowed. Allowed extensions: {', '.join(app.config['ALLOWED_EXTENSIONS'])}", "error")
        return None

    conn = None
    photo_path = None # Define photo_path to be accessible in except block
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file_extension = os.path.splitext(s_filename)[1] # Get extension from secured name
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        photo_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)

        # Save the file stream directly to the path.
        photo_file_storage.save(photo_path)
        print(f"Photo saved to: {photo_path}")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO photos (album_id, filename, notes) VALUES (?, ?, ?)",
            (album_id, unique_filename, notes)
        )
        conn.commit()
        new_photo_id = cursor.lastrowid
        flash(f"Photo '{s_filename}' uploaded successfully!", "success") # Use s_filename here
        return new_photo_id
    except sqlite3.Error as e:
        print(f"Database error uploading photo: {e}")
        flash(f"Database error uploading photo: {e}", "error")
        if os.path.exists(photo_path): # Clean up if DB error
             os.remove(photo_path)
        return None
    except IOError as e:
        print(f"File error uploading photo: {e}")
        flash(f"File error uploading photo: {e}", "error")
        return None
    finally:
        if conn:
            conn.close()


def get_photos_in_album(album_id: int) -> list[sqlite3.Row]:
    """
    Retrieves all photos associated with a specific album ID.

    Args:
        album_id: The ID of the album whose photos are to be retrieved.

    Returns:
        A list of sqlite3.Row objects, each representing a photo.
        Ordered by upload date (descending). Returns empty list if none found or error.
    """
    # (Code from previous steps)
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM photos WHERE album_id = ? ORDER BY upload_date DESC", (album_id,))
        photos = cursor.fetchall()
        return photos
    except sqlite3.Error as e:
        print(f"Error fetching photos for album: {e}")
        return []
    finally:
        if conn:
            conn.close()

# --- Flask Routes ---
@app.route('/')
def index():
    """Route for the homepage. Displays all albums."""
    albums = get_all_albums()
    return render_template('index.html', albums=albums, theme=get_color_theme(), themes=ALLOWED_THEMES)

@app.route('/create_album', methods=['POST'])
def create_album_route():
    """Route to handle creation of a new album via POST request."""
    name = request.form.get('album_name')
    if name:
        album_id = create_album(name)
        if album_id:
            flash(f"Album '{name}' created successfully!", "success")
        else:
            flash(f"Failed to create album '{name}'.", "error")
    else:
        flash("Album name cannot be empty.", "warning")
    return redirect(url_for('index'))

@app.route('/album/<int:album_id>')
def album_view(album_id: int):
    """Route to view a specific album and its photos."""
    album = get_album_by_id(album_id)
    if not album:
        flash(f"Album with ID {album_id} not found.", "error")
        return redirect(url_for('index'))
    photos = get_photos_in_album(album_id)
    return render_template('album_view.html', album=album, photos=photos, theme=get_color_theme(), themes=ALLOWED_THEMES)

@app.route('/album/<int:album_id>/upload', methods=['POST'])
def upload_photo_route(album_id: int):
    """Route to handle photo uploads to a specific album via POST request."""
    album = get_album_by_id(album_id)
    if not album:
        flash(f"Album with ID {album_id} not found. Cannot upload photo.", "error")
        return redirect(url_for('index'))

    notes = request.form.get('notes', '')
    photo_file = request.files.get('photo')

    # Basic check if the file object exists
    if not photo_file:
        flash("No file part in the request.", "error")
        return redirect(url_for('album_view', album_id=album_id))

    # Check if a file was actually selected (filename is not empty)
    if not photo_file.filename: # An empty filename typically means no file was chosen
        flash("No file selected for upload.", "error")
        return redirect(url_for('album_view', album_id=album_id))

    # upload_photo function now takes the FileStorage object directly
    # and will handle secure_filename and saving internally.
    upload_photo(album_id, photo_file, notes)
    return redirect(url_for('album_view', album_id=album_id))


@app.route('/uploads/<filename>')
def uploaded_file(filename: str):
    """Route to serve uploaded files (photos) from the UPLOAD_FOLDER."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/theme/set/<theme_name>')
def set_theme_route(theme_name: str):
    """Route to set the application's color theme."""
    if set_color_theme(theme_name):
        flash(f"Theme changed to {theme_name}.", "info")
    else:
        flash(f"Invalid theme: {theme_name}.", "warning")

    # Try to redirect to referrer, fallback to index
    referrer = request.referrer
    if referrer:
        return redirect(referrer)
    return redirect(url_for('index'))

# --- Email and Zip Functions (from previous steps, not directly used by UI yet) ---
def create_zip_of_photos(photo_filenames: list[str], zip_filename: str) -> str | None:
    os.makedirs(TEMP_ZIP_DIR, exist_ok=True)
    zip_file_path = os.path.join(TEMP_ZIP_DIR, zip_filename)
    # ... (rest of the function from previous step, ensure UPLOADS_DIR is app.config['UPLOAD_FOLDER'] or equivalent)
    # This function is not directly exposed via UI routes in the current setup,
    # but is available for programmatic use or future extension.
    try:
        with zipfile.ZipFile(zip_file_path, 'w') as zf:
            for photo_filename in photo_filenames:
                full_photo_path = os.path.join(app.config['UPLOAD_FOLDER'], photo_filename) # Use app.config
                if os.path.exists(full_photo_path):
                    zf.write(full_photo_path, arcname=photo_filename)
                else:
                    print(f"Warning: Photo {photo_filename} not found at {full_photo_path}. Skipping.")
        return zip_file_path
    except Exception as e:
        print(f"Error creating zip file {zip_filename}: {e}")
        if os.path.exists(zip_file_path): os.remove(zip_file_path)
        return None


def send_email_with_attachment(recipient_email: str, subject: str, body: str, attachment_path: str) -> bool:
    """
    Simulates sending an email with an attachment.
    In a real application, this would connect to an SMTP server.
    Currently, it prints details to the console.

    Args:
        recipient_email: The email address of the recipient.
        subject: The subject of the email.
        body: The plain text body of the email.
        attachment_path: The filesystem path to the file to be attached.

    Returns:
        True if the simulation was successful (or email sent, in a real scenario),
        False otherwise (e.g., attachment not found).
    """
    # ... (rest of the function from previous step)
    if not os.path.exists(attachment_path): return False
    # Placeholder SMTP details
    # ...
    print(f"Simulating email to {recipient_email} with attachment {attachment_path}") # Simulation
    return True


def parse_exam_docx(docx_path):
    """
    Parses a .docx file to extract exam questions and answers.
    """
    try:
        document = docx.Document(docx_path)
        questions = []
        current_question = None

        for para in document.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # Assuming questions end with a '?'
            if text.endswith('?'):
                if current_question:
                    questions.append(current_question)
                current_question = {'question': text, 'answers': []}
            elif current_question:
                is_correct = '✅' in text
                text = text.replace('✅', '').replace('❌', '').strip()
                current_question['answers'].append({'text': text, 'correct': is_correct})

        if current_question:
            questions.append(current_question)

        return questions
    except Exception as e:
        flash(f"Error parsing Word document: {e}", "error")
        return []

@app.route('/exam/upload', methods=['GET', 'POST'])
def upload_exam_route():
    if request.method == 'POST':
        if 'exam_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['exam_file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            questions = parse_exam_docx(filepath)
            return render_template('exam.html', questions=questions, theme=get_color_theme(), themes=ALLOWED_THEMES)
        else:
            flash('Allowed file types are docx', 'error')
            return redirect(request.url)

    return render_template('upload_exam.html', theme=get_color_theme(), themes=ALLOWED_THEMES)


if __name__ == '__main__':
    print("Starting Flask application...")
    init_db() # Ensure database and required directories are initialized before running the app
    # The main execution block for running the Flask development server.
    # Debug mode should be disabled in a production environment.
    app.run(debug=True, host='0.0.0.0', port=5001)
