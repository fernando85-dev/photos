import unittest
import os
import sqlite3
import shutil
import io
import sys
import zipfile

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import main # Import the main module from app package
from werkzeug.utils import secure_filename # For use with MockFileStorage if needed

# MockFileStorage Class
class MockFileStorage:
    def __init__(self, filename, data, content_type='application/octet-stream'):
        self.filename = filename
        self.stream = io.BytesIO(data)
        self.content_type = content_type
        # Add a read method to mimic FileStorage's stream reading behavior
        self.read = self.stream.read

    def save(self, dst):
        # Ensure the directory exists before saving
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # Must reset stream position before reading/writing if read multiple times
        self.stream.seek(0)
        with open(dst, 'wb') as f:
            f.write(self.read())

class TestAppLogic(unittest.TestCase):

    def setUp(self):
        """Set up test environment before each test."""
        self.original_db_file = main.DATABASE_FILE
        self.original_uploads_dir = main.UPLOADS_DIR
        self.original_temp_zip_dir = main.TEMP_ZIP_DIR
        self.original_allowed_extensions = main.app.config['ALLOWED_EXTENSIONS'].copy()
        self.original_current_theme = main.CURRENT_THEME
        self.original_allowed_themes = main.ALLOWED_THEMES.copy()


        self.test_dir = os.path.join(os.path.dirname(__file__), 'test_data_temp')
        self.test_db_file = os.path.join(self.test_dir, 'test_database.db')
        self.test_uploads_dir = os.path.join(self.test_dir, 'test_uploads')
        self.test_temp_zip_dir = os.path.join(self.test_dir, 'test_zips')

        # Create test directories
        os.makedirs(self.test_dir, exist_ok=True)
        os.makedirs(self.test_uploads_dir, exist_ok=True)
        os.makedirs(self.test_temp_zip_dir, exist_ok=True)

        # Patch module-level variables in main
        main.DATABASE_FILE = self.test_db_file
        main.UPLOADS_DIR = self.test_uploads_dir
        main.TEMP_ZIP_DIR = self.test_temp_zip_dir
        main.app.config['UPLOAD_FOLDER'] = self.test_uploads_dir # Flask app uses this
        main.app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'png', 'txt', 'gif'} # Include txt for testing

        # Initialize the database in the test directory
        main.init_db()

        # Reset theme for each test
        main.CURRENT_THEME = 'white'
        main.ALLOWED_THEMES = ['white', 'black', 'test_theme']


    def tearDown(self):
        """Clean up test environment after each test."""
        main.DATABASE_FILE = self.original_db_file
        main.UPLOADS_DIR = self.original_uploads_dir
        main.TEMP_ZIP_DIR = self.original_temp_zip_dir
        main.app.config['UPLOAD_FOLDER'] = self.original_uploads_dir
        main.app.config['ALLOWED_EXTENSIONS'] = self.original_allowed_extensions
        main.CURRENT_THEME = self.original_current_theme
        main.ALLOWED_THEMES = self.original_allowed_themes


        # Remove the test directory and its contents
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_database_connection(self):
        """Test database connection and basic table existence."""
        conn = main.get_db_connection()
        self.assertIsNotNone(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='albums';")
        self.assertIsNotNone(cursor.fetchone(), "Albums table should exist.")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='photos';")
        self.assertIsNotNone(cursor.fetchone(), "Photos table should exist.")
        conn.close()

    def test_02_create_and_get_album(self):
        """Test album creation and retrieval."""
        album_name = "Test Album"
        album_id = main.create_album(album_name)
        self.assertIsNotNone(album_id, "Album creation should return an ID.")

        retrieved_album = main.get_album_by_id(album_id)
        self.assertIsNotNone(retrieved_album, "Should retrieve created album by ID.")
        self.assertEqual(retrieved_album['name'], album_name)

        all_albums = main.get_all_albums()
        self.assertEqual(len(all_albums), 1)
        self.assertEqual(all_albums[0]['name'], album_name)

        # Test creating another album
        main.create_album("Album Two")
        all_albums = main.get_all_albums()
        self.assertEqual(len(all_albums), 2)


    def test_03_upload_and_get_photo(self):
        """Test photo upload, file saving, and retrieval."""
        album_id = main.create_album("Photo Album")
        self.assertIsNotNone(album_id)

        photo_filename = "test_image.jpg"
        photo_data = b"fake JPEG data"
        notes = "This is a test photo."

        mock_file = MockFileStorage(photo_filename, photo_data)

        # We need a Flask app context for flash messages if they are used by upload_photo
        with main.app.test_request_context():
            photo_id = main.upload_photo(album_id, mock_file, notes)

        self.assertIsNotNone(photo_id, "Photo upload should return an ID.")

        photos_in_album = main.get_photos_in_album(album_id)
        self.assertEqual(len(photos_in_album), 1)
        uploaded_photo_record = photos_in_album[0]
        self.assertEqual(uploaded_photo_record['notes'], notes)

        # Check if file was saved
        # The filename in DB is uuid.ext, original_filename is not directly stored.
        db_filename = uploaded_photo_record['filename']
        expected_photo_path = os.path.join(self.test_uploads_dir, db_filename)
        self.assertTrue(os.path.exists(expected_photo_path), f"Photo file should exist at {expected_photo_path}")

        with open(expected_photo_path, 'rb') as f:
            saved_data = f.read()
        self.assertEqual(saved_data, photo_data)

    def test_04_upload_invalid_file_type(self):
        """Test uploading a file with a disallowed extension."""
        album_id = main.create_album("Invalid Upload Test Album")
        self.assertIsNotNone(album_id)

        # .pdf is not in our test ALLOWED_EXTENSIONS {'jpg', 'png', 'txt', 'gif'}
        mock_file = MockFileStorage("document.pdf", b"some pdf data")

        with main.app.test_request_context(): # For flash messages
            photo_id = main.upload_photo(album_id, mock_file, "Attempting PDF upload")

        self.assertIsNone(photo_id, "Uploading a disallowed file type should return None.")
        photos_in_album = main.get_photos_in_album(album_id)
        self.assertEqual(len(photos_in_album), 0, "No photo should be added to DB for disallowed type.")

    def test_05_theme_settings(self):
        """Test theme getting and setting functions."""
        self.assertEqual(main.get_color_theme(), "white") # Default or reset in setUp

        self.assertTrue(main.set_color_theme("black"))
        self.assertEqual(main.get_color_theme(), "black")

        self.assertTrue(main.set_color_theme("test_theme"))
        self.assertEqual(main.get_color_theme(), "test_theme")

        self.assertFalse(main.set_color_theme("non_existent_theme"))
        self.assertEqual(main.get_color_theme(), "test_theme") # Should remain unchanged

    def test_06_allowed_file(self):
        """Test the allowed_file helper function."""
        self.assertTrue(main.allowed_file("photo.jpg"))
        self.assertTrue(main.allowed_file("image.PNG")) # Check case-insensitivity
        self.assertTrue(main.allowed_file("document.txt")) # txt is in test allowed list
        self.assertFalse(main.allowed_file("archive.zip"))
        self.assertFalse(main.allowed_file("script.exe"))
        self.assertFalse(main.allowed_file("no_extension"))
        self.assertTrue(main.allowed_file(".startswithdot.jpg")) # allowed_file itself should permit this

    def test_07_create_zip_of_photos(self):
        """Test creating a zip file of photos."""
        album_id = main.create_album("Zip Test Album")
        self.assertIsNotNone(album_id)

        # Upload a photo to be zipped
        photo_data = b"zip me"
        mock_jpg = MockFileStorage("photo_for_zip.jpg", photo_data)
        with main.app.test_request_context():
            photo_id_jpg = main.upload_photo(album_id, mock_jpg, "Photo for zipping")
        self.assertIsNotNone(photo_id_jpg)

        photos = main.get_photos_in_album(album_id)
        self.assertEqual(len(photos), 1)
        db_photo_filename = photos[0]['filename']

        zip_filename = "test_archive.zip"
        zip_path = main.create_zip_of_photos([db_photo_filename], zip_filename)

        self.assertIsNotNone(zip_path, "create_zip_of_photos should return the path to the zip.")
        self.assertTrue(os.path.exists(zip_path), f"Zip file should exist at {zip_path}")
        self.assertEqual(os.path.basename(zip_path), zip_filename)
        self.assertEqual(os.path.dirname(zip_path), self.test_temp_zip_dir)

        # Verify contents of the zip file
        with zipfile.ZipFile(zip_path, 'r') as zf:
            self.assertEqual(len(zf.namelist()), 1, "Zip file should contain one photo.")
            self.assertIn(db_photo_filename, zf.namelist(), "Uploaded photo's filename should be in the zip.")
            # Check file content
            with zf.open(db_photo_filename) as unzipped_file:
                self.assertEqual(unzipped_file.read(), photo_data)

        # Test with a non-existent photo
        zip_path_fail = main.create_zip_of_photos(["nonexistent.jpg"], "fail.zip")
        # This might still create an empty zip or return None depending on implementation
        # Current main.py prints warning and continues, creating empty/partial zip.
        # For robustness, it should ideally return None if no valid files are added.
        # Let's assume for now it might create an empty zip.
        if zip_path_fail: # If it creates a zip
             with zipfile.ZipFile(zip_path_fail, 'r') as zf_fail:
                self.assertEqual(len(zf_fail.namelist()), 0)


    def test_08_send_email_simulation(self):
        """Test the email sending simulation."""
        # Create a dummy attachment file for the test
        dummy_attachment_path = os.path.join(self.test_temp_zip_dir, "dummy_attachment.zip")
        with open(dummy_attachment_path, "w") as f:
            f.write("This is a dummy zip file.")

        self.assertTrue(os.path.exists(dummy_attachment_path))

        result = main.send_email_with_attachment(
            recipient_email="test@example.com",
            subject="Test Email",
            body="This is a test email body.",
            attachment_path=dummy_attachment_path
        )
        self.assertTrue(result, "Email sending simulation should return True.")

        # Test with non-existent attachment
        result_fail = main.send_email_with_attachment("test@example.com", "S", "B", "nonexistent.zip")
        self.assertFalse(result_fail, "Email sim with non-existent attachment should fail.")


if __name__ == '__main__':
    unittest.main()
