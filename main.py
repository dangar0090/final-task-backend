import os
from dotenv import load_dotenv
import boto3
from flask import Flask, request, jsonify
import psycopg2
from psycopg2 import sql, errors
from flask_cors import CORS

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# AWS S3 configuration
s3 = boto3.client(
    's3',
    region_name='us-east-1',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

bucket_name = os.getenv('S3_BUCKET_NAME')

# Database configuration
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=os.getenv('DB_PORT'),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cursor = conn.cursor()

# Allowed file extensions
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.doc', '.docx', '.odt', '.ods', '.odp'}

def get_real_ip():
    # Check for forwarded headers first
    if 'X-Forwarded-For' in request.headers:
        # Take the first IP in the list
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    return request.remote_addr

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        file = request.files['file']
        user_ip = get_real_ip()
        file_size = os.fstat(file.fileno()).st_size
        filename, file_extension = os.path.splitext(file.filename)

        # Check if the file extension is allowed
        if file_extension.lower() not in ALLOWED_EXTENSIONS:
            return jsonify({"error": f"Extension '{file_extension}' is not allowed"}), 400

        # Upload to S3
        s3.upload_fileobj(file, bucket_name, file.filename)

        # Insert into DB
        try:
            cursor.execute(
                sql.SQL("INSERT INTO public.users (filename, \"user-ip\", extension, \"file-size\") VALUES (%s, %s, %s, %s)")
                    .format(),
                (filename, f"{user_ip}/32", file_extension, file_size)
            )
            conn.commit()
            return jsonify({"message": "File uploaded successfully"}), 200

        except errors.UniqueViolation:
            conn.rollback()
            return jsonify({"error": "Duplicate filename found"}), 409

        except Exception as db_error:
            conn.rollback()
            app.logger.error(f"Database error: {str(db_error)}")
            return jsonify({"error": str(db_error)}), 500

    except Exception as e:
        app.logger.error(f"Error uploading file: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)