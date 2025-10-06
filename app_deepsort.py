# app_deepsort.py
import os
# Force CPU (no GPU)
os.environ["CUDA_VISIBLE_DEVICES"] = ""

from flask import Flask, render_template, Response, jsonify, request, redirect, url_for, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import cv2, mysql.connector, datetime, jwt
from collections import OrderedDict
import numpy as np

# YOLOv8
from ultralytics import YOLO
# DeepSORT
from deep_sort_realtime.deepsort_tracker import DeepSort

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["ALLOWED_EXTENSIONS"] = {"mp4", "avi", "mov", "mkv"}
app.config["SECRET_KEY"] = "your_secret_key"

# ----------------- DATABASE CONNECTION -----------------
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",
        database="zone_app_db"
    )

# ----------------- JWT HELPERS -----------------
def generate_jwt(username):
    payload = {
        "user": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=2)
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")

def verify_jwt(token):
    try:
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        return decoded["user"]
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

def require_login(func):
    def wrapper(*args, **kwargs):
        token = request.cookies.get("token")
        if not token:
            return redirect(url_for("login"))
        user = verify_jwt(token)
        if not user:
            return redirect(url_for("login"))
        return func(user, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# ----------------- GLOBAL ZONE COUNTS -----------------
zone_counts_global = {}

# ----------------- AUTH -----------------
@app.route("/")
def home():
    return redirect(url_for("login"))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        email = request.form["email"]
        contact = request.form["contact"]

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=%s OR email=%s", (username, email))
        if cursor.fetchone():
            conn.close()
            return "User or Email already exists!"

        hashed_pw = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (username, password, email, contact) VALUES (%s, %s, %s, %s)",
            (username, hashed_pw, email, contact)
        )
        conn.commit()
        conn.close()
        return redirect(url_for("login"))

    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            token = generate_jwt(username)
            resp = make_response(redirect(url_for("welcome")))
            resp.set_cookie("token", token, httponly=True, samesite="Strict")
            return resp

        return "Invalid username or password!"
    return render_template("login.html")

@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for("login")))
    resp.delete_cookie("token")
    return resp

@app.route("/welcome")
@require_login
def welcome(user):
    return render_template("welcome.html", username=user)

# ----------------- DASHBOARD -----------------
@app.route("/dashboard")
@require_login
def dashboard(user):
    return render_template("index.html")

@app.route("/dashboard3")
@require_login
def dashboard3(user):
    return render_template("dashboard.html")

# ----------------- VIDEO SOURCE -----------------
camera = None
yolo_model = YOLO("yolov8m.pt")
try:
    yolo_model.to("cpu")
except:
    pass

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]

@app.route("/set_source", methods=["POST"])
@require_login
def set_source(user):
    global camera
    source_type = request.form.get("source")

    if source_type == "webcam":
        if camera: camera.release()
        camera = cv2.VideoCapture(0)
        return jsonify({"status": "webcam selected"})

    if "file" in request.files:
        file = request.files["file"]
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            if camera: camera.release()
            camera = cv2.VideoCapture(filepath)
            return jsonify({"status": f"video {filename} selected"})

    return jsonify({"error": "Invalid source"}), 400

# ----------------- DEEPSORT TRACKER -----------------
deepsort_tracker = DeepSort(max_age=30)
print("[INFO] Using DeepSORT tracker only")

# ----------------- VIDEO STREAM -----------------
@app.route("/video_feed")
@require_login
def video_feed(user):
    def generate():
        global camera, zone_counts_global
        shrink_factor = 0.6  # Change this to adjust box size

        while True:
            if camera is None:
                continue
            success, frame = camera.read()
            if not success:
                camera.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            # YOLO detections
            results = yolo_model(frame, classes=[0], conf=0.35)
            boxes = []
            for r in results[0].boxes:
                coords = r.xyxy[0].cpu().numpy() if hasattr(r.xyxy[0], 'cpu') else np.array(r.xyxy[0])
                x1, y1, x2, y2 = map(int, coords[:4])
                conf = float(r.conf[0]) if hasattr(r, 'conf') else float(r.conf) if hasattr(r, 'conf') else 0.0
                boxes.append((x1, y1, x2, y2, conf))

            # Fetch zones
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM zones_data")
            zones = cursor.fetchall()
            conn.close()
            zone_counts_global = {z['zone_name']: 0 for z in zones}

            # DeepSORT tracking
            detections_ds = [([x1, y1, x2, y2], conf, "person") for x1, y1, x2, y2, conf in boxes]
            tracks = deepsort_tracker.update_tracks(detections_ds, frame=frame)

            for tr in tracks:
                if not tr.is_confirmed(): 
                    continue
                track_id = tr.track_id
                ltrb = getattr(tr, "to_ltrb", lambda: None)()
                if ltrb is None: 
                    continue
                x1, y1, x2, y2 = map(int, ltrb)

                # Shrink box
                w = x2 - x1
                h = y2 - y1
                x1_new = x1 + int(w * shrink_factor / 2)
                y1_new = y1 + int(h * shrink_factor / 2)
                x2_new = x2 - int(w * shrink_factor / 2)
                y2_new = y2 - int(h * shrink_factor / 2)

                cv2.rectangle(frame, (x1_new, y1_new), (x2_new, y2_new), (0, 255, 0), 2)
                cv2.putText(frame, f"ID {track_id}", (x1_new, y1_new - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                # Zone counting
                for z in zones:
                    zx1, zy1, zx2, zy2 = z['top_left_x'], z['top_left_y'], z['bottom_right_x'], z['bottom_right_y']
                    if max(zx1, x1_new) < min(zx2, x2_new) and max(zy1, y1_new) < min(zy2, y2_new):
                        zone_counts_global[z['zone_name']] += 1

            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret: continue
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

# ----------------- ZONES CRUD -----------------
@app.route("/save_zone", methods=["POST"])
@require_login
def save_zone(user):
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO zones_data (zone_name, top_left_x, top_left_y, bottom_right_x, bottom_right_y) VALUES (%s, %s, %s, %s, %s)",
        (data['label'], data['topleft']['x'], data['topleft']['y'], data['bottomright']['x'], data['bottomright']['y'])
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route("/get_zones")
@require_login
def get_zones(user):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM zones_data")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{
        "label": r['zone_name'],
        "topleft": {"x": r['top_left_x'], "y": r['top_left_y']},
        "bottomright": {"x": r['bottom_right_x'], "y": r['bottom_right_y']}
    } for r in rows])

@app.route("/delete_zone", methods=["POST"])
@require_login
def delete_zone(user):
    label = request.json.get('label')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM zones_data WHERE zone_name=%s", (label,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route("/update_zone", methods=["POST"])
@require_login
def update_zone(user):
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE zones_data SET top_left_x=%s, top_left_y=%s, bottom_right_x=%s, bottom_right_y=%s WHERE zone_name=%s",
        (data['topleft']['x'], data['topleft']['y'], data['bottomright']['x'], data['bottomright']['y'], data['label'])
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})

# ----------------- LIVE COUNTS -----------------
@app.route("/get_counts")
@require_login
def get_counts(user):
    global zone_counts_global
    alert_message = None
    for zone, count in zone_counts_global.items():
        if count > 10:
            alert_message = f"⚠️ High occupancy in {zone}! ({count} people)"
            break
    return jsonify({"counts": zone_counts_global, "alert": alert_message})

# ----------------- MAIN -----------------
if __name__ == "__main__":
    if not os.path.exists("uploads"):
        os.makedirs("uploads")
    app.run(debug=True)
