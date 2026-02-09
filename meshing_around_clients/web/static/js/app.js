/**
 * Meshing-Around Web Client JavaScript
 * Provides real-time updates via WebSocket and UI interactions
 */

// Global state
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_BASE_DELAY = 1000;
const MAX_MESSAGE_LENGTH = 228;

// Pong tracking for dead connection detection
let lastPongTime = 0;
let heartbeatInterval = null;

// CSRF token helper - reads from csrf_token cookie
function getCsrfToken() {
    const match = document.cookie.match(/(^|;\s*)csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[2]) : '';
}

// Toast notification system
function showToast(message, type = 'info', duration = 3000) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    // Trigger reflow for animation
    toast.offsetHeight;
    toast.classList.add('toast-visible');

    setTimeout(() => {
        toast.classList.remove('toast-visible');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Initialize WebSocket connection with exponential backoff
function initWebSocket() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        return; // Already connected or connecting
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        lastPongTime = Date.now();
        updateConnectionStatus(true);
        showToast('Connected to mesh network', 'success');
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);

        // Exponential backoff reconnect
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttempts++;
            const delay = Math.min(RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts - 1), 30000);
            console.log(`Reconnecting in ${delay}ms... attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}`);
            setTimeout(initWebSocket, delay);
        } else {
            showToast('Connection lost. Click to retry.', 'error', 10000);
            // Allow manual reconnect by clicking the connection indicator
            const indicator = document.getElementById('connection-indicator');
            if (indicator) {
                indicator.style.cursor = 'pointer';
                indicator.onclick = () => {
                    reconnectAttempts = 0;
                    initWebSocket();
                    indicator.onclick = null;
                    indicator.style.cursor = '';
                };
            }
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
            lastPongTime = Date.now();
            break;
        case 'message_status':
            handleMessageStatus(msg);
            break;
        default:
            console.log('Unknown message type:', msg.type);
    }
}

// Handle send message status response
function handleMessageStatus(msg) {
    if (msg.success) {
        showToast('Message sent', 'success', 2000);
    } else {
        showToast(msg.error || 'Failed to send message', 'error');
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

// Update nodes table (dashboard - top 10)
function updateNodesTable(nodes) {
    const tbody = document.getElementById('nodes-body');
    if (!tbody) return;

    if (!nodes || nodes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-message">No nodes found</td></tr>';
        return;
    }

    // Sort: online first, then by last heard
    nodes.sort((a, b) => {
        if (a.is_online !== b.is_online) return b.is_online ? 1 : -1;
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
    const isEmergency = msg.text && ['emergency', '911', 'sos', 'mayday'].some(
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

    // Also update full messages list if on messages page
    const fullList = document.getElementById('full-messages-list');
    if (fullList) {
        const newMsgHtml = renderMessage(msg, true);
        fullList.insertAdjacentHTML('afterbegin', newMsgHtml);
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

    // Show toast for new alerts
    showToast(`Alert: ${alert.title || 'New alert'}`, alert.severity >= 3 ? 'error' : 'warning');
}

// Update node data
function updateNodeData(node, isNew) {
    // Refresh stats
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            updateElement('stat-online', data.online_nodes);
            updateElement('stat-total', data.node_count);
        })
        .catch(e => console.error('Failed to fetch status:', e));

    // Refresh the nodes table if we're on the nodes page
    const fullNodesBody = document.getElementById('full-nodes-body');
    if (fullNodesBody) {
        fetch('/api/nodes')
            .then(r => r.json())
            .then(data => updateFullNodesTable(data.nodes))
            .catch(e => console.error('Failed to fetch nodes:', e));
    }

    if (isNew) {
        showToast(`New node discovered: ${node.display_name || node.node_id}`, 'info', 4000);
    }
}

// Send a message with client-side validation
function sendMessage(text, destination = '^all', channel = 0) {
    // Client-side validation
    if (!text || !text.trim()) {
        showToast('Message cannot be empty', 'warning');
        return;
    }
    if (text.length > MAX_MESSAGE_LENGTH) {
        showToast(`Message too long (${text.length}/${MAX_MESSAGE_LENGTH})`, 'warning');
        return;
    }

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
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': getCsrfToken()
            },
            body: JSON.stringify({
                text: text,
                destination: destination,
                channel: channel
            })
        }).then(r => {
            if (!r.ok) return r.json().then(data => { throw new Error(data.detail || 'Failed to send'); });
            showToast('Message sent', 'success', 2000);
        }).catch(e => {
            console.error('Send failed:', e);
            showToast(e.message || 'Failed to send message', 'error');
        });
    }
}

// Setup character counter on message input fields
function setupCharCounter(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;

    // Create counter element
    const counter = document.createElement('span');
    counter.className = 'char-counter';
    counter.textContent = `0/${MAX_MESSAGE_LENGTH}`;
    input.parentElement.style.position = 'relative';
    input.insertAdjacentElement('afterend', counter);

    input.addEventListener('input', () => {
        const len = input.value.length;
        counter.textContent = `${len}/${MAX_MESSAGE_LENGTH}`;
        counter.className = 'char-counter' + (len > MAX_MESSAGE_LENGTH ? ' char-counter-over' : len > MAX_MESSAGE_LENGTH * 0.9 ? ' char-counter-warn' : '');
    });

    // Enforce max length
    input.setAttribute('maxlength', MAX_MESSAGE_LENGTH);
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Start heartbeat with pong verification
function startHeartbeat() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);

    lastPongTime = Date.now();
    heartbeatInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            // Check if we received a pong since last ping
            const timeSincePong = Date.now() - lastPongTime;
            if (timeSincePong > 60000) {
                // No pong in 60s - connection is likely dead
                console.warn('No pong received in 60s, closing stale connection');
                ws.close();
                return;
            }
            ws.send(JSON.stringify({type: 'ping'}));
        }
    }, 30000);
}

// Initialize dashboard page
function initDashboard() {
    initWebSocket();
    startHeartbeat();

    // Setup send message form
    const sendBtn = document.getElementById('send-btn');
    const msgInput = document.getElementById('message-input');
    const channelSelect = document.getElementById('channel-select');

    if (sendBtn && msgInput) {
        setupCharCounter('message-input');

        sendBtn.addEventListener('click', () => {
            const text = msgInput.value.trim();
            if (text) {
                const channel = channelSelect ? parseInt(channelSelect.value) : 0;
                sendMessage(text, '^all', channel);
                msgInput.value = '';
                // Reset char counter
                const counter = msgInput.parentElement.querySelector('.char-counter');
                if (counter) counter.textContent = `0/${MAX_MESSAGE_LENGTH}`;
            }
        });

        msgInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendBtn.click();
            }
        });
    }
}

// Initialize nodes page
function initNodesPage() {
    initWebSocket();
    startHeartbeat();

    fetch('/api/nodes')
        .then(r => r.json())
        .then(data => updateFullNodesTable(data.nodes))
        .catch(e => {
            console.error('Failed to load nodes:', e);
            showToast('Failed to load nodes', 'error');
        });
}

// Initialize messages page
function initMessagesPage() {
    initWebSocket();
    startHeartbeat();

    setupCharCounter('full-message-input');

    fetch('/api/messages')
        .then(r => r.json())
        .then(data => updateFullMessagesList(data.messages))
        .catch(e => {
            console.error('Failed to load messages:', e);
            showToast('Failed to load messages', 'error');
        });
}

// Initialize alerts page
function initAlertsPage() {
    initWebSocket();
    startHeartbeat();

    fetch('/api/alerts')
        .then(r => r.json())
        .then(data => updateAlertsTable(data))
        .catch(e => {
            console.error('Failed to load alerts:', e);
            showToast('Failed to load alerts', 'error');
        });
}

// Auto-initialize based on page
document.addEventListener('DOMContentLoaded', function() {
    // Check which page we're on and initialize accordingly
    const path = window.location.pathname;

    if (path === '/' || path === '/index.html') {
        initDashboard();
    }
    // Other pages have their own init in the template

    // Setup mobile nav toggle
    const navToggle = document.getElementById('nav-toggle');
    const navLinks = document.getElementById('nav-links');
    if (navToggle && navLinks) {
        navToggle.addEventListener('click', () => {
            navLinks.classList.toggle('nav-open');
            navToggle.setAttribute('aria-expanded',
                navLinks.classList.contains('nav-open') ? 'true' : 'false');
        });
    }
});
