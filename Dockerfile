# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the requirements file into the container
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
# Using --no-cache-dir to reduce image size
# Using --default-timeout to prevent timeouts if network is slow
# Using --retries to make it more resilient
RUN pip install --no-cache-dir --default-timeout=100 --retries=5 -r requirements.txt

# Copy the application code (app directory and any other necessary top-level files if they existed)
# For this project, only the 'app' directory contains the application code.
COPY ./app ./app

# Application specific environment variables
# FLASK_APP is useful for flask command line, but we run main.py directly
# ENV FLASK_APP app/main.py
ENV FLASK_RUN_HOST 0.0.0.0
ENV FLASK_RUN_PORT 5001
# Set PYTHONUNBUFFERED to ensure print statements are sent straight to terminal
ENV PYTHONUNBUFFERED 1


# Expose the port the app runs on (as defined by FLASK_RUN_PORT)
EXPOSE 5001

# The application's init_db() function, called at the start of main.py,
# will create the database file inside /usr/src/app/app/database.db
# and the UPLOADS_DIR (/usr/src/project_root/uploads -> /usr/src/app/uploads)
# and TEMP_ZIP_DIR (/usr/src/app/app/tmp_zip_files).
# The Dockerfile assumes that the application handles creation of these directories.
# The UPLOADS_DIR is defined in main.py as os.path.join(PROJECT_ROOT_DIR, 'uploads')
# Inside the container, PROJECT_ROOT_DIR will be /usr/src/app.
# So, UPLOADS_DIR will be /usr/src/app/uploads. This directory needs to be
# writeable by the user running the python process.
# The base python images usually run as root, so this should be fine.
# If running as non-root, ensure /usr/src/app (or specifically /usr/src/app/uploads) is writable.

# Run main.py when the container launches
# This will also execute init_db() as it's in the main.py's "if __name__ == '__main__':" block
CMD ["python", "app/main.py"]
