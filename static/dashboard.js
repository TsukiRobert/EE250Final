// dashboard.js This is made from GPT 

let eventTypeChart = null;

async function fetchStatus() {
    const res = await fetch("/latest_status");
    const data = await res.json();

    const stateDiv = document.getElementById("currentState");
    stateDiv.innerHTML = `<span class="label">State:</span> <span class="value">${data.current_state}</span>`;

    // caption: prefer live_caption, fallback to last event
    const caption = data.live_caption || data.last_event_caption || "N/A";
    document.getElementById("latestCaption").innerHTML =
        `<span class="label">Caption:</span> <span class="value">${caption}</span>`;

    // threat image + name
    const img = document.getElementById("threatImage");
    const threatMeta = document.getElementById("threatMeta");

    let src = null;
    if (data.threat_image) {
        src = data.threat_image;
    } else if (data.threat_snapshot_b64) {
        src = "data:image/jpeg;base64," + data.threat_snapshot_b64;
    }

    if (data.threat_flag && src) {
        img.src = src;
        img.style.display = "block";
        threatMeta.textContent = `Threat: ${data.threat_name || "unknown"}`;
    } else {
        img.style.display = "none";
        threatMeta.textContent = "Threat: none";
    }

    // panel background
    const panel = document.getElementById("livePanel");
    panel.classList.remove("state-idle", "state-event", "state-threat");
    if (data.threat_flag) {
        panel.classList.add("state-threat");
    } else if (data.current_state === "event_active") {
        panel.classList.add("state-event");
    } else {
        panel.classList.add("state-idle");
    }
}

// ========== 2. EVENTS / TIMELINE ==========
async function fetchEvents() {
    const res = await fetch("/events?limit=100");
    const events = await res.json();

    updateTimeline(events);
    updateEventTable(events);
    updateEventTypeChart(events);
}

function updateEventTable(events) {
    const tbody = document.querySelector("#eventTable tbody");
    tbody.innerHTML = "";

    // newest first
    events.sort((a, b) => b.event_id - a.event_id);

    for (let ev of events) {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${ev.event_id}</td>
            <td>${ev.event_type}</td>
            <td>${ev.start_time}</td>
            <td>${ev.end_time}</td>
            <td>${(ev.duration_sec || 0).toFixed(1)}</td>
            <td>${ev.caption || ""}</td>
        `;
        tbody.appendChild(tr);
    }
}

function updateTimeline(events) {
    const container = document.getElementById("timelineContainer");
    container.innerHTML = "";

    // left→right in time
    events.sort((a, b) => a.event_id - b.event_id);

    for (let ev of events) {
        const bar = document.createElement("div");
        bar.className = `timeline-bar ${ev.event_type}`;

        const dur = ev.duration_sec || 1;
        bar.style.width = Math.min(dur * 25, 300) + "px";

        bar.title = `${ev.event_type} (${dur.toFixed(1)}s)`;
        container.appendChild(bar);
    }
}

// ========== 3. ANALYTICS CHART ==========
function updateEventTypeChart(events) {
    const counts = { visitor: 0, delivery: 0, threat: 0 };
    for (let ev of events) {
        if (counts[ev.event_type] !== undefined) {
            counts[ev.event_type] += 1;
        }
    }

    const ctx = document.getElementById("eventTypeChart").getContext("2d");
    if (eventTypeChart) {
        eventTypeChart.destroy();
    }

    eventTypeChart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: ["Visitor", "Delivery", "Threat"],
            datasets: [{
                label: "Event count",
                data: [counts.visitor, counts.delivery, counts.threat]
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 } }
            }
        }
    });
}

// ========== 4. DANGER LIST ==========
async function fetchDangerList() {
    const res = await fetch("/danger_list");
    const data = await res.json();
    const list = data.dangerous_persons || [];

    document.getElementById("dangerList").textContent =
        list.length ? list.join(", ") : "(none)";
}

async function removeDanger() {
    const name = document.getElementById("dangerName").value;
    if (!name) return;

    await fetch("/danger_list", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "remove", name })
    });

    document.getElementById("dangerName").value = "";
    fetchDangerList();
}

// acknowledge button
async function ackAlert() {
    await fetch("/ack_alert", { method: "POST" });
}

// ========== AUTO REFRESH ==========
setInterval(() => {
    fetchStatus();
    fetchEvents();
    fetchDangerList();
}, 1500);

// initial load
fetchStatus();
fetchEvents();
fetchDangerList();
