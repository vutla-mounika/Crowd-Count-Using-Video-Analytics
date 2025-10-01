// ================================
// CANVAS DRAWING FOR ZONES
// ================================
let canvas = document.getElementById('canvas');
let ctx = canvas.getContext('2d');
let drawing = false;
let startX, startY, endX, endY;

let editCanvas = document.getElementById('editCanvas');
let editCtx = editCanvas.getContext('2d');
let editing = false;
let editStartX, editStartY, editEndX, editEndY;
let editingZoneLabel = null;

// ================================
// VIDEO SOURCE SELECTION
// ================================
async function uploadVideo() {
    let form = document.getElementById("uploadForm");
    let formData = new FormData(form);
    const res = await fetch("/set_source", { method: "POST", body: formData });
    const data = await res.json();
    alert(data.status || data.error);
}

async function useWebcam() {
    const formData = new FormData();
    formData.append("source", "webcam");
    const res = await fetch("/set_source", { method: "POST", body: formData });
    const data = await res.json();
    alert(data.status || data.error);
}

// ================================
// ZONE DRAWING
// ================================
function startDraw() {
    let video = document.getElementById("videoFeed");
    let canvas = document.getElementById("canvas");

    // Force reload the stream if hidden before
    video.src = "/video_feed?" + new Date().getTime();
    video.style.display = "block";
    canvas.style.display = "block";

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    startX = startY = endX = endY = null;

    canvas.onmousedown = e => {
        drawing = true;
        startX = e.offsetX;
        startY = e.offsetY;
    };

    canvas.onmousemove = e => {
        if (drawing) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            endX = e.offsetX;
            endY = e.offsetY;
            ctx.strokeStyle = 'red';
            ctx.lineWidth = 2;
            ctx.strokeRect(startX, startY, endX - startX, endY - startY);
        }
    };

    canvas.onmouseup = e => {
        drawing = false;
        endX = e.offsetX;
        endY = e.offsetY;

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = 'red';
        ctx.lineWidth = 2;
        ctx.strokeRect(startX, startY, endX - startX, endY - startY);
    };
}

// ================================
// SAVE ZONE
// ================================
function saveZone() {
    let label = document.getElementById('zoneLabel').value;
    if (!label || startX == null || endX == null) {
        alert('Enter a label and draw a zone first.');
        return;
    }

    let zone = {
        label: label,
        topleft: { x: Math.min(startX, endX), y: Math.min(startY, endY) },
        bottomright: { x: Math.max(startX, endX), y: Math.max(startY, endY) }
    };

    fetch('/save_zone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(zone)
    }).then(res => res.json()).then(() => {
        alert('Zone saved!');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        startX = startY = endX = endY = null;  // reset
        loadZones();
        drawPreviewZones();
    });
}

// ================================
// LOAD ZONES
// ================================
async function loadZones() {
    const res = await fetch('/get_zones');
    const zones = await res.json();

    const selectDelete = document.getElementById('zoneSelect');
    const selectEdit = document.getElementById('editZoneSelect');
    selectDelete.innerHTML = "";
    selectEdit.innerHTML = "";

    if (zones.length === 0) {
        let opt1 = document.createElement("option");
        opt1.textContent = "No zones available";
        selectDelete.appendChild(opt1);

        let opt2 = document.createElement("option");
        opt2.textContent = "No zones available";
        selectEdit.appendChild(opt2);
    } else {
        zones.forEach(z => {
            let option1 = document.createElement("option");
            option1.value = z.label;
            option1.textContent = z.label;
            selectDelete.appendChild(option1);

            let option2 = document.createElement("option");
            option2.value = z.label;
            option2.textContent = z.label;
            selectEdit.appendChild(option2);
        });
    }
}

// ================================
// DRAW PREVIEW ZONES
// ================================
async function drawPreviewZones() {
    const res = await fetch('/get_zones');
    const zones = await res.json();

    let previewCanvas = document.getElementById("previewCanvas");
    let pctx = previewCanvas.getContext("2d");
    pctx.clearRect(0, 0, previewCanvas.width, previewCanvas.height);

    zones.forEach(z => {
        pctx.strokeStyle = "red";
        pctx.lineWidth = 2;
        pctx.strokeRect(z.topleft.x, z.topleft.y,
                        z.bottomright.x - z.topleft.x,
                        z.bottomright.y - z.topleft.y);

        pctx.fillStyle = "red";
        pctx.font = "14px Arial";
        pctx.fillText(z.label, z.topleft.x, z.topleft.y - 5);
    });
}

// ================================
// DELETE ZONE
// ================================
async function deleteZone() {
    const select = document.getElementById('zoneSelect');
    const label = select.value;

    if (!label || label === "No zones available") {
        alert("Please select a valid zone to delete.");
        return;
    }

    const confirmDelete = confirm(`Delete zone: ${label}?`);
    if (!confirmDelete) return;

    await fetch('/delete_zone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: label })
    });

    alert("Zone deleted successfully!");
    loadZones();
    drawPreviewZones();
}

// ================================
// EDIT ZONE
// ================================
async function editZone() {
    const select = document.getElementById('editZoneSelect');
    const label = select.value;

    if (!label || label === "No zones available") {
        alert("Please select a valid zone to edit.");
        return;
    }

    editingZoneLabel = label;
    document.getElementById("editArea").style.display = "block";

    editCtx.clearRect(0, 0, editCanvas.width, editCanvas.height);

    // Fetch all zones and find the selected one
    const res = await fetch('/get_zones');
    const zones = await res.json();
    const selectedZone = zones.find(z => z.label === label);

    if (selectedZone) {
        editStartX = selectedZone.topleft.x;
        editStartY = selectedZone.topleft.y;
        editEndX = selectedZone.bottomright.x;
        editEndY = selectedZone.bottomright.y;

        editCtx.strokeStyle = 'blue';
        editCtx.lineWidth = 2;
        editCtx.strokeRect(
            editStartX,
            editStartY,
            editEndX - editStartX,
            editEndY - editStartY
        );
    }

    // Allow redraw
    editCanvas.onmousedown = e => {
        editing = true;
        editStartX = e.offsetX;
        editStartY = e.offsetY;
    };

    editCanvas.onmousemove = e => {
        if (editing) {
            editCtx.clearRect(0, 0, editCanvas.width, editCanvas.height);
            editEndX = e.offsetX;
            editEndY = e.offsetY;
            editCtx.strokeStyle = 'blue';
            editCtx.lineWidth = 2;
            editCtx.strokeRect(editStartX, editStartY, editEndX - editStartX, editEndY - editStartY);
        }
    };

    editCanvas.onmouseup = e => {
        editing = false;
        editEndX = e.offsetX;
        editEndY = e.offsetY;

        editCtx.clearRect(0, 0, editCanvas.width, editCanvas.height);
        editCtx.strokeStyle = 'blue';
        editCtx.lineWidth = 2;
        editCtx.strokeRect(editStartX, editStartY, editEndX - editStartX, editEndY - editStartY);
    };
}

// ================================
// SAVE EDITED ZONE
// ================================
async function saveEditedZone() {
    if (!editingZoneLabel) {
        alert("No zone selected to update.");
        return;
    }

    let updatedZone = {
        label: editingZoneLabel,
        topleft: { x: Math.min(editStartX, editEndX), y: Math.min(editStartY, editEndY) },
        bottomright: { x: Math.max(editStartX, editEndX), y: Math.max(editStartY, editEndY) }
    };

    await fetch('/update_zone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedZone)
    });

    alert("Zone updated successfully!");
    document.getElementById("editArea").style.display = "none";
    loadZones();
    drawPreviewZones();
}


