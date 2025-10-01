let lineChart, barChart, heatmapChart;

// Init charts
function initCharts() {
    // Line Chart
    const ctx1 = document.getElementById("lineChart").getContext("2d");
    lineChart = new Chart(ctx1, {
        type: "line",
        data: { labels: [], datasets: [] },
        options: { responsive: true, plugins:{legend:{position:"bottom"}} }
    });

    // Bar Chart
    const ctx2 = document.getElementById("barChart").getContext("2d");
    barChart = new Chart(ctx2, {
        type: "bar",
        data: { labels: [], datasets: [{ label:"Occupancy", backgroundColor:"steelblue", data: [] }] },
        options: { responsive: true, plugins:{legend:{display:false}} }
    });

    // Heatmap Bubble Chart
    const hctx = document.getElementById("heatmapChart").getContext("2d");
    heatmapChart = new Chart(hctx, {
        type: "bubble",
        data: { datasets: [] },
        options: {
            scales: {
                x: { beginAtZero: true, title: { display: true, text: "Zones" } },
                y: { beginAtZero: true, title: { display: true, text: "People Count" } }
            },
            plugins: { legend: { display: false } }
        }
    });
}

// Update dashboard
async function fetchData() {
    const res = await fetch("/get_counts");
    const data = await res.json();
    const counts = data.counts || {};

    // 🚨 Show alert if threshold exceeded
    const alertBox = document.getElementById("alertBox");
    if (data.alert) {
        alertBox.innerText = data.alert;
        alertBox.style.display = "block";
    } else {
        alertBox.style.display = "none";
    }

    // Analytics Cards
    const totalPeople = Object.values(counts).reduce((a, b) => a + b, 0);
    const activeZones = Object.keys(counts).length;
    const maxZone = Object.entries(counts).reduce((a, b) => a[1] > b[1] ? a : b, ["None", 0]);

    document.getElementById("analyticsCards").innerHTML = `
        <div class="card"><h3>Total People</h3><p><b>${totalPeople}</b></p></div>
        <div class="card"><h3>Active Zones</h3><p><b>${activeZones}</b></p></div>
        <div class="card"><h3>Busiest Zone</h3><p><b>${maxZone[0]} (${maxZone[1]})</b></p></div>
    `;

    // Zone Occupancy Table
    const table = document.getElementById("occupancyTable");
    table.innerHTML = "";
    for (const [zone, count] of Object.entries(counts)) {
        table.innerHTML += `<tr><td>${zone}</td><td style="text-align:right;font-weight:bold;">${count}</td></tr>`;
    }

    // Line Chart
    const now = new Date().toLocaleTimeString();
    if (lineChart.data.labels.length > 10) {
        lineChart.data.labels.shift();
        lineChart.data.datasets.forEach(ds => ds.data.shift());
    }
    lineChart.data.labels.push(now);
    Object.entries(counts).forEach(([zone, count]) => {
        let ds = lineChart.data.datasets.find(d => d.label === zone);
        if (!ds) {
            ds = { label: zone, data: [], borderColor: randomColor(), fill:false };
            lineChart.data.datasets.push(ds);
        }
        ds.data.push(count);
    });
    lineChart.update();

    // Bar Chart
    barChart.data.labels = Object.keys(counts);
    barChart.data.datasets[0].data = Object.values(counts);
    barChart.update();

    // Heatmap Bubble Chart
    const keys = Object.keys(counts);
    const values = Object.values(counts);

    heatmapChart.data.datasets = keys.map((zone, i) => ({
        label: zone,
        data: [{ x: i + 1, y: values[i], r: values[i] * 2 + 5 }],
        backgroundColor: values[i] > 20 ? "rgba(231,76,60,0.7)" :
                          values[i] > 10 ? "rgba(243,156,18,0.7)" :
                                           "rgba(46,204,113,0.7)"
    }));
    heatmapChart.update();
}

function randomColor() {
    return "hsl(" + Math.floor(Math.random()*360) + ",70%,50%)";
}

initCharts();
setInterval(fetchData, 3000);
fetchData();
