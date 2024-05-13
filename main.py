import os
import json
import boto3
import logging
from flask import Flask, request, jsonify
import psycopg2
from psycopg2 import sql, errors
from flask_cors import CORS
from botocore.exceptions import ClientError

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Define a function to get secrets from AWS Secrets Manager
def get_secret(secret_name):
    region_name = "us-east-1"  # Specify your region

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        logger.error("Error fetching secret '{}': {}".format(secret_name, str(e)))
        raise e

    secret = get_secret_value_response['SecretString']
    return json.loads(secret)

# Fetch secrets from AWS Secrets Manager
secret_name = 'env-backend-to-db'  # Specify your secret name
try:
    secret_dict = get_secret(secret_name)
    for key, value in secret_dict.items():
        if isinstance(value, str):
            # Set environment variables
            os.environ[key] = value
except Exception as e:
    logger.error("Error setting up environment variables: {}".format(str(e)))
    raise e

# Database configuration
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=os.getenv('DB_PORT'),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cursor = conn.cursor()

# Create users table if not exists
try:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS public.users
        (
            filename character varying(255) NOT NULL,
            "user-ip" cidr NOT NULL,
            extension character varying(255) NOT NULL,
            "file-size" integer NOT NULL,
            PRIMARY KEY (filename),
            UNIQUE (filename)
        )
    """)
    conn.commit()
except Exception as create_table_error:
    conn.rollback()
    logger.error("Error creating table: {}".format(str(create_table_error)))

# Allowed file extensions
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.doc', '.docx', '.odt', '.ods', '.odp'}

def get_real_ip():
    # Check for forwarded headers first
    if 'X-Forwarded-For' in request.headers:
        # Take the first IP in the list
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    return request.remote_addr
    
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'}), 200

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        file = request.files['file']
        user_ip = get_real_ip()
        file_size = os.fstat(file.fileno()).st_size
        filename, file_extension = os.path.splitext(file.filename)

        # Check if the file extension is allowed
        if file_extension.lower() not in ALLOWED_EXTENSIONS:
            return jsonify({"error": "Extension '{}' is not allowed".format(file_extension)}), 400

        # Insert into DB
        try:
            cursor.execute(
                sql.SQL("INSERT INTO public.users (filename, \"user-ip\", extension, \"file-size\") VALUES (%s, %s, %s, %s)")
                    .format(),
                (filename, "{}/32".format(user_ip), file_extension, file_size)
            )
            conn.commit()
            return jsonify({"message": "File uploaded successfully"}), 200

        except errors.UniqueViolation:
            conn.rollback()
            return jsonify({"error": "Duplicate filename found"}), 409

        except Exception as db_error:
            conn.rollback()
            logger.error("Database error: {}".format(str(db_error)))
            return jsonify({"error": str(db_error)}), 500

    except Exception as e:
        logger.error("Error uploading file: {}".format(str(e)))
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
