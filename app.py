from flask import Flask, render_template, Response, jsonify, request, redirect, url_for, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import cv2, mysql.connector, os, datetime, jwt
from collections import OrderedDict
import numpy as np
from ultralytics import YOLO   # ✅ YOLOv8 for person detection

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["ALLOWED_EXTENSIONS"] = {"mp4", "avi", "mov", "mkv"}
app.config["SECRET_KEY"] = "your_secret_key"   # ✅ JWT Secret

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
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
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

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        if cursor.fetchone():
            conn.close()
            return "User already exists!"

        hashed_pw = generate_password_hash(password)
        cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_pw))
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

# ----------------- DASHBOARD ROUTES -----------------
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
yolo_model = YOLO("yolov8m.pt")   # ✅ Medium YOLOv8 for better detection

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

# ----------------- TRACKER -----------------
class CentroidTracker:
    def __init__(self, maxDisappeared=40):
        self.nextObjectID = 1
        self.objects = OrderedDict()
        self.disappeared = OrderedDict()
        self.maxDisappeared = maxDisappeared

    def register(self, centroid):
        self.objects[self.nextObjectID] = centroid
        self.disappeared[self.nextObjectID] = 0
        self.nextObjectID += 1

    def deregister(self, objectID):
        del self.objects[objectID]
        del self.disappeared[objectID]

    def update(self, rects):
        if len(rects) == 0:
            for objectID in list(self.disappeared.keys()):
                self.disappeared[objectID] += 1
                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)
            return self.objects

        inputCentroids = np.zeros((len(rects), 2), dtype="int")
        for (i, (x, y, w, h)) in enumerate(rects):
            cX = int(x + w / 2.0)
            cY = int(y + h / 2.0)
            inputCentroids[i] = (cX, cY)

        if len(self.objects) == 0:
            for i in range(0, len(inputCentroids)):
                self.register(inputCentroids[i])
        else:
            objectIDs = list(self.objects.keys())
            objectCentroids = list(self.objects.values())

            D = np.linalg.norm(np.array(objectCentroids)[:, None] - inputCentroids, axis=2)
            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            usedRows, usedCols = set(), set()
            for (row, col) in zip(rows, cols):
                if row in usedRows or col in usedCols:
                    continue
                objectID = objectIDs[row]
                self.objects[objectID] = inputCentroids[col]
                self.disappeared[objectID] = 0
                usedRows.add(row)
                usedCols.add(col)

            unusedRows = set(range(0, D.shape[0])).difference(usedRows)
            unusedCols = set(range(0, D.shape[1])).difference(usedCols)

            for row in unusedRows:
                objectID = objectIDs[row]
                self.disappeared[objectID] += 1
                if self.disappeared[objectID] > self.maxDisappeared:
                    self.deregister(objectID)

            for col in unusedCols:
                self.register(inputCentroids[col])

        return self.objects

tracker = CentroidTracker()

# ----------------- VIDEO STREAM -----------------
@app.route("/video_feed")
@require_login
def video_feed(user):
    def generate():
        global camera, zone_counts_global
        while True:
            if camera is None:
                continue
            success, frame = camera.read()
            if not success:
                camera.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            results = yolo_model(frame, classes=[0], conf=0.3)

            boxes = []
            for r in results[0].boxes:
                x1, y1, x2, y2 = map(int, r.xyxy[0])
                w, h = x2 - x1, y2 - y1
                boxes.append((x1, y1, w, h))

            objects = tracker.update(boxes)

            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM zones_data")
            zones = cursor.fetchall()
            conn.close()
            zone_counts_global = {z['zone_name']: 0 for z in zones}

            for (objectID, centroid) in objects.items():
                cX, cY = centroid
                matched_box = None
                for (x, y, w, h) in boxes:
                    if x <= cX <= x + w and y <= cY <= y + h:
                        matched_box = (x, y, w, h)
                        break
                if matched_box:
                    (x, y, w, h) = matched_box
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    cv2.putText(frame, f"ID {objectID}", (x, y - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                    for z in zones:
                        zx1, zy1 = z['top_left_x'], z['top_left_y']
                        zx2, zy2 = z['bottom_right_x'], z['bottom_right_y']
                        px1, py1, px2, py2 = x, y, x + w, y + h

                        overlap_x1 = max(zx1, px1)
                        overlap_y1 = max(zy1, py1)
                        overlap_x2 = min(zx2, px2)
                        overlap_y2 = min(zy2, py2)

                        if overlap_x1 < overlap_x2 and overlap_y1 < overlap_y2:
                            zone_counts_global[z['zone_name']] += 1

            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

# ----------------- ZONES CRUD -----------------
@app.route("/save_zone", methods=["POST"])
@require_login
def save_zone(user):
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO zones_data (zone_name, top_left_x, top_left_y, bottom_right_x, bottom_right_y) "
        "VALUES (%s, %s, %s, %s, %s)",
        (data['label'], data['topleft']['x'], data['topleft']['y'],
         data['bottomright']['x'], data['bottomright']['y'])
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
    zones = []
    for r in rows:
        zones.append({
            "label": r['zone_name'],
            "topleft": {"x": r['top_left_x'], "y": r['top_left_y']},
            "bottomright": {"x": r['bottom_right_x'], "y": r['bottom_right_y']}
        })
    return jsonify(zones)

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
        (data['topleft']['x'], data['topleft']['y'],
         data['bottomright']['x'], data['bottomright']['y'],
         data['label'])
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})

# ----------------- LIVE COUNTS ENDPOINT -----------------
@app.route("/get_counts")
@require_login
def get_counts(user):
    global zone_counts_global
    if not zone_counts_global:
        zone_counts_global = {}

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
