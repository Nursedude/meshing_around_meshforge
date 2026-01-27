/**
 * Meshing-Around Web Client JavaScript
 * Provides real-time updates via WebSocket and UI interactions
 */

// Global state
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_DELAY = 3000;

// Initialize WebSocket connection
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        updateConnectionStatus(true);
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);

        // Attempt to reconnect
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttempts++;
            console.log(`Reconnecting... attempt ${reconnectAttempts}`);
            setTimeout(initWebSocket, RECONNECT_DELAY);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWebSocketMessage(msg);
        } catch (e) {
            console.error('Error parsing WebSocket message:', e);
        }
    };
}

// Handle incoming WebSocket messages
function handleWebSocketMessage(msg) {
    switch (msg.type) {
        case 'init':
        case 'refresh':
            updateDashboard(msg.data);
            break;
        case 'message':
            addNewMessage(msg.data);
            break;
        case 'alert':
            addNewAlert(msg.data);
            break;
        case 'node_update':
        case 'node_new':
            updateNodeData(msg.data, msg.type === 'node_new');
            break;
        case 'pong':
            // Heartbeat response
            break;
        default:
            console.log('Unknown message type:', msg.type);
    }
}

// Update connection status indicator
function updateConnectionStatus(connected) {
    const indicator = document.getElementById('connection-indicator');
    const text = document.getElementById('connection-text');

    if (indicator) {
        indicator.className = `indicator ${connected ? 'connected' : 'disconnected'}`;
    }
    if (text) {
        text.textContent = connected ? 'Connected' : 'Disconnected';
    }

    const statusIcon = document.getElementById('status-icon');
    if (statusIcon) {
        statusIcon.className = `stat-icon status-icon ${connected ? 'connected' : 'disconnected'}`;
    }
}

// Update dashboard with full network data
function updateDashboard(data) {
    // Update stats
    updateElement('stat-status', data.connection_status || 'Unknown');
    updateElement('stat-my-node', data.my_node_id || 'N/A');
    updateElement('stat-online', data.online_node_count || 0);
    updateElement('stat-total', data.total_node_count || 0);
    updateElement('stat-messages', data.messages?.length || 0);
    updateElement('stat-alerts', data.unread_alert_count || 0);

    // Update network info
    updateElement('net-interface', data.connection_status || '--');
    updateElement('net-channels', data.channel_count || 8);

    // Update nodes table
    if (data.nodes) {
        updateNodesTable(Object.values(data.nodes));
    }

    // Update messages list
    if (data.messages) {
        updateMessagesList(data.messages);
    }

    // Update alerts list
    if (data.alerts) {
        updateAlertsList(data.alerts);
    }
}

// Helper to safely update element text
function updateElement(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
    }
}

// Update nodes table
function updateNodesTable(nodes) {
    const tbody = document.getElementById('nodes-body');
    if (!tbody) return;

    if (!nodes || nodes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-message">No nodes found</td></tr>';
        return;
    }

    // Sort by last heard
    nodes.sort((a, b) => {
        const aTime = a.last_heard ? new Date(a.last_heard) : new Date(0);
        const bTime = b.last_heard ? new Date(b.last_heard) : new Date(0);
        return bTime - aTime;
    });

    tbody.innerHTML = nodes.slice(0, 10).map(node => `
        <tr>
            <td>
                ${node.is_favorite ? '<span class="status-badge favorite">★</span>' : ''}
                ${escapeHtml(node.display_name || node.node_id)}
            </td>
            <td>${escapeHtml(node.time_since_heard || 'Never')}</td>
            <td>${renderBattery(node.telemetry?.battery_level)}</td>
            <td>${node.telemetry?.snr?.toFixed(1) || '-'} dB</td>
        </tr>
    `).join('');
}

// Update full nodes table (for nodes page)
function updateFullNodesTable(nodes) {
    const tbody = document.getElementById('full-nodes-body');
    if (!tbody) return;

    if (!nodes || nodes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="empty-message">No nodes found</td></tr>';
        return;
    }

    tbody.innerHTML = nodes.map(node => `
        <tr onclick="showNodeDetails('${escapeHtml(node.node_id)}')" style="cursor: pointer;">
            <td>
                <span class="status-badge ${node.is_online ? 'online' : 'offline'}">
                    ${node.is_online ? 'Online' : 'Offline'}
                </span>
            </td>
            <td><code>${escapeHtml(node.node_id)}</code></td>
            <td>${escapeHtml(node.display_name)}</td>
            <td>${escapeHtml(node.hardware_model)}</td>
            <td>${escapeHtml(node.role)}</td>
            <td>${escapeHtml(node.time_since_heard)}</td>
            <td>${renderBattery(node.telemetry?.battery_level)}</td>
            <td>${node.telemetry?.snr?.toFixed(1) || '-'} dB</td>
            <td>${node.telemetry?.rssi || '-'}</td>
            <td>${node.hop_count || 0}</td>
            <td>${formatPosition(node.position)}</td>
        </tr>
    `).join('');
}

// Render battery indicator
function renderBattery(level) {
    if (!level || level === 0) return '-';

    const className = level > 50 ? 'battery-high' :
                      level > 20 ? 'battery-medium' : 'battery-low';

    return `
        <div class="battery-indicator">
            <div class="battery-bar">
                <div class="battery-level ${className}" style="width: ${level}%"></div>
            </div>
            <span>${level}%</span>
        </div>
    `;
}

// Format position
function formatPosition(pos) {
    if (!pos || (pos.latitude == null && pos.longitude == null)) return 'N/A';
    return `${pos.latitude?.toFixed(4)}, ${pos.longitude?.toFixed(4)}`;
}

// Update messages list
function updateMessagesList(messages) {
    const list = document.getElementById('messages-list');
    if (!list) return;

    if (!messages || messages.length === 0) {
        list.innerHTML = '<div class="empty-message">No messages yet</div>';
        return;
    }

    const recentMessages = messages.slice(-10).reverse();
    list.innerHTML = recentMessages.map(msg => renderMessage(msg)).join('');
}

// Update full messages list (for messages page)
function updateFullMessagesList(messages) {
    const list = document.getElementById('full-messages-list');
    if (!list) return;

    if (!messages || messages.length === 0) {
        list.innerHTML = '<div class="empty-message">No messages</div>';
        return;
    }

    list.innerHTML = messages.slice().reverse().map(msg => renderMessage(msg, true)).join('');
}

// Render a single message
function renderMessage(msg, detailed = false) {
    const isEmergency = msg.text && ['emergency', '911', 'sos', 'help'].some(
        kw => msg.text.toLowerCase().includes(kw)
    );

    let className = 'message-item';
    if (!msg.is_incoming) className += ' outgoing';
    if (isEmergency) className += ' emergency';

    let html = `
        <div class="${className}">
            <div class="message-header">
                <span class="message-sender">${escapeHtml(msg.sender_name || msg.sender_id)}</span>
                <span class="message-time">${msg.time_formatted || ''}</span>
            </div>
            <div class="message-text">${escapeHtml(msg.text)}</div>
    `;

    if (detailed) {
        html += `
            <div class="message-meta">
                <span>Ch: ${msg.channel}</span>
                <span>To: ${msg.is_broadcast ? 'All' : escapeHtml(msg.recipient_id)}</span>
                <span>SNR: ${msg.snr?.toFixed(1) || '-'}</span>
                <span>Hops: ${msg.hop_count || 0}</span>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

// Add a new message to the list
function addNewMessage(msg) {
    const list = document.getElementById('messages-list');
    if (list) {
        const newMsgHtml = renderMessage(msg);
        list.insertAdjacentHTML('afterbegin', newMsgHtml);

        // Limit displayed messages
        while (list.children.length > 15) {
            list.removeChild(list.lastChild);
        }
    }

    // Update message count
    const countEl = document.getElementById('stat-messages');
    if (countEl) {
        countEl.textContent = parseInt(countEl.textContent || 0) + 1;
    }
}

// Update alerts list
function updateAlertsList(alerts) {
    const list = document.getElementById('alerts-list');
    if (!list) return;

    if (!alerts || alerts.length === 0) {
        list.innerHTML = '<div class="empty-message">No alerts</div>';
        return;
    }

    const recentAlerts = alerts.slice(-5).reverse();
    list.innerHTML = recentAlerts.map(alert => renderAlert(alert)).join('');
}

// Update alerts table (for alerts page)
function updateAlertsTable(data) {
    updateElement('alert-total', data.total || 0);
    updateElement('alert-unread', data.unread || 0);

    const tbody = document.getElementById('alerts-body');
    if (!tbody) return;

    const alerts = data.alerts || [];
    if (alerts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-message">No alerts</td></tr>';
        return;
    }

    tbody.innerHTML = alerts.slice().reverse().map(alert => `
        <tr>
            <td>${alert.timestamp ? new Date(alert.timestamp).toLocaleString() : '-'}</td>
            <td><span class="status-badge severity-${alert.severity}">${escapeHtml(alert.severity_label)}</span></td>
            <td>${escapeHtml(alert.alert_type)}</td>
            <td>${escapeHtml(alert.title)}</td>
            <td>${escapeHtml(alert.message)}</td>
            <td>${escapeHtml(alert.source_node || '-')}</td>
            <td>${alert.acknowledged ? '✓' : '✗'}</td>
            <td>
                ${!alert.acknowledged ? `<button class="btn btn-secondary" onclick="acknowledgeAlert('${alert.id}')">Ack</button>` : ''}
            </td>
        </tr>
    `).join('');
}

// Render a single alert
function renderAlert(alert) {
    return `
        <div class="alert-item severity-${alert.severity}">
            <div class="alert-header">
                <span class="alert-title">${escapeHtml(alert.title)}</span>
                <span class="alert-type">${escapeHtml(alert.alert_type)}</span>
            </div>
            <div class="alert-message">${escapeHtml(alert.message)}</div>
        </div>
    `;
}

// Add a new alert
function addNewAlert(alert) {
    const list = document.getElementById('alerts-list');
    if (list) {
        const newAlertHtml = renderAlert(alert);
        list.insertAdjacentHTML('afterbegin', newAlertHtml);

        while (list.children.length > 5) {
            list.removeChild(list.lastChild);
        }
    }

    // Update alert count
    const countEl = document.getElementById('stat-alerts');
    if (countEl) {
        countEl.textContent = parseInt(countEl.textContent || 0) + 1;
    }
}

// Update node data
function updateNodeData(node, isNew) {
    // Refresh stats
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            updateElement('stat-online', data.online_nodes);
            updateElement('stat-total', data.node_count);
        });

    // Could also refresh the nodes table if we're on the nodes page
    const fullNodesBody = document.getElementById('full-nodes-body');
    if (fullNodesBody) {
        fetch('/api/nodes')
            .then(r => r.json())
            .then(data => updateFullNodesTable(data.nodes));
    }
}

// Send a message
function sendMessage(text, destination = '^all', channel = 0) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'send_message',
            text: text,
            destination: destination,
            channel: channel
        }));
    } else {
        // Fallback to REST API
        fetch('/api/messages/send', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                text: text,
                destination: destination,
                channel: channel
            })
        }).then(r => {
            if (!r.ok) throw new Error('Failed to send');
        }).catch(e => {
            console.error('Send failed:', e);
            alert('Failed to send message');
        });
    }
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize dashboard page
function initDashboard() {
    initWebSocket();

    // Setup send message form
    const sendBtn = document.getElementById('send-btn');
    const msgInput = document.getElementById('message-input');
    const channelSelect = document.getElementById('channel-select');

    if (sendBtn && msgInput) {
        sendBtn.addEventListener('click', () => {
            const text = msgInput.value.trim();
            if (text) {
                const channel = channelSelect ? parseInt(channelSelect.value) : 0;
                sendMessage(text, '^all', channel);
                msgInput.value = '';
            }
        });

        msgInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendBtn.click();
            }
        });
    }

    // Heartbeat to keep connection alive
    setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({type: 'ping'}));
        }
    }, 30000);
}

// Initialize nodes page
function initNodesPage() {
    initWebSocket();

    fetch('/api/nodes')
        .then(r => r.json())
        .then(data => updateFullNodesTable(data.nodes));
}

// Initialize messages page
function initMessagesPage() {
    initWebSocket();

    fetch('/api/messages')
        .then(r => r.json())
        .then(data => updateFullMessagesList(data.messages));
}

// Initialize alerts page
function initAlertsPage() {
    initWebSocket();

    fetch('/api/alerts')
        .then(r => r.json())
        .then(data => updateAlertsTable(data));
}

// Auto-initialize based on page
document.addEventListener('DOMContentLoaded', function() {
    // Check which page we're on and initialize accordingly
    const path = window.location.pathname;

    if (path === '/' || path === '/index.html') {
        initDashboard();
    }
    // Other pages have their own init in the template
});
